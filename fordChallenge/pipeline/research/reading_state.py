"""Estado serializável de leitura, separado dos candidatos e de sua aprovação.

Concluir uma passagem significa que o provedor respondeu com sucesso, inclusive
quando não encontrou valores. Não significa que o documento comprova um campo.
"""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

STATE_VERSION = 1
PARSER_VERSION = "text-blocks-1"


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    ).hexdigest()


def hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def block_id(index: int, text: str) -> str:
    """A posição diferencia ocorrências distintas de um mesmo texto repetido."""
    return f"{index}:{hash_text(text)}"


@dataclass
class EstadoLeitura:
    """Registro de contextos; o checkpoint deve salvar candidatos na mesma operação.

    O extrator fornece identidade completa, hashes, versões e campos. A classe
    não acessa rede, banco ou arquivo e nunca armazena uma resposta como fato.
    """

    contextos: dict[str, dict] = field(default_factory=dict)

    def contexto(self, identidade: dict, blocos: list[str]) -> tuple[str, dict]:
        # Tuplas do asdict(VehicleTarget), por exemplo, viram listas no checkpoint.
        # Canonicalize já na primeira chamada para a igualdade sobreviver ao JSON.
        identidade = json.loads(json.dumps(identidade, ensure_ascii=False, allow_nan=False))
        key = digest(identidade)
        if key not in self.contextos:
            self.contextos[key] = {
                "identidade": copy.deepcopy(identidade),
                "blocos": list(blocos),
                "sucessos": {},
                "escalonamentos": {},
                "tentativas": {},
            }
        context = self.contextos[key]
        if context["identidade"] != identidade or context["blocos"] != blocos:
            raise ValueError("estado de leitura não corresponde ao documento/blocos")
        return key, context

    def to_dict(self) -> dict:
        return {"version": STATE_VERSION, "contextos": copy.deepcopy(self.contextos)}

    def invalidar_fonte(self, source_id: str) -> None:
        """Invalidate completed passes together with the source's removed candidates."""
        self.contextos = {
            key: context
            for key, context in self.contextos.items()
            if context.get("identidade", {}).get("source_id") != source_id
        }

    @classmethod
    def from_dict(cls, payload: dict | None) -> EstadoLeitura:
        if payload is None:
            return cls()
        if not isinstance(payload, dict) or payload.get("version") != STATE_VERSION:
            raise ValueError("versão inválida do estado de leitura")
        contexts = payload.get("contextos")
        if not isinstance(contexts, dict):
            raise ValueError("contextos de leitura inválidos")
        for key, context in contexts.items():
            try:
                if not isinstance(context, dict) or key != digest(context["identidade"]):
                    raise ValueError("identidade divergente no estado de leitura")
                blocks = context["blocos"]
                if not isinstance(blocks, list) or len(set(blocks)) != len(blocks):
                    raise ValueError("blocos de leitura inválidos")
                for item in blocks:
                    index, sha = item.split(":", 1)
                    if (
                        not index.isdigit()
                        or len(sha) != 64
                        or any(c not in "0123456789abcdef" for c in sha)
                    ):
                        raise ValueError("identificador de bloco inválido")
                allowed = {f"{b}:{phase}" for b in blocks for phase in ("small", "large")}
                for name in ("sucessos", "tentativas"):
                    if not isinstance(context[name], dict) or not set(context[name]) <= allowed:
                        raise ValueError("passagem de leitura desconhecida")
                for record in context["sucessos"].values():
                    if (
                        not isinstance(record, dict)
                        or not isinstance(record.get("campos"), list)
                        or not all(isinstance(f, str) for f in record["campos"])
                    ):
                        raise ValueError("conclusão de leitura inválida")
                for record in context["tentativas"].values():
                    if (
                        not isinstance(record, dict)
                        or not isinstance(record.get("quantidade"), int)
                        or record["quantidade"] < 1
                    ):
                        raise ValueError("tentativa de leitura inválida")
                escalations = context["escalonamentos"]
                if not isinstance(escalations, dict) or not set(escalations) <= set(blocks):
                    raise ValueError("escalonamento de leitura inválido")
                for b, fields in escalations.items():
                    if (
                        f"{b}:small" not in context["sucessos"]
                        or not isinstance(fields, list)
                        or not all(isinstance(f, str) for f in fields)
                    ):
                        raise ValueError("escalonamento sem primeira passagem concluída")
                for task in context["sucessos"]:
                    if task.endswith(":large") and task.removesuffix(":large") not in escalations:
                        raise ValueError("segunda passagem sem escalonamento")
                    expected_fields = (
                        escalations[task.removesuffix(":large")]
                        if task.endswith(":large")
                        else context["identidade"]["campos_llm"]
                    )
                    record = context["sucessos"][task]
                    if not expected_fields or record["campos"] != expected_fields:
                        raise ValueError("conclusão pertence a outros campos")
                    if context["tentativas"].get(task, {}).get("ok") is not True:
                        raise ValueError("conclusão sem tentativa bem-sucedida")
            except (KeyError, TypeError, AttributeError) as exc:
                raise ValueError("estado de leitura malformado") from exc
        return cls(copy.deepcopy(contexts))


def pendente(context: dict, block: str) -> str | None:
    if f"{block}:small" not in context["sucessos"]:
        return "small"
    if block in context["escalonamentos"] and f"{block}:large" not in context["sucessos"]:
        return "large"
    return None


def tentativa(context: dict, task: str, *, ok: bool, motivo: str) -> None:
    previous = context["tentativas"].get(task, {})
    # Motivos são códigos/descrições locais do extrator, não mensagens do provedor
    # que poderiam conter cabeçalhos ou informações da conta.
    context["tentativas"][task] = {
        "quantidade": previous.get("quantidade", 0) + 1,
        "ok": ok,
        "motivo": motivo,
    }


def resumo(
    key: str, context: dict, *, usados: list[str], concluidos: list[str], falhas: list[dict]
) -> dict:
    remaining = sum(pendente(context, b) is not None for b in context["blocos"])
    return {
        "contexto_id": key,
        "total": len(context["blocos"]),
        "concluidos": len(context["blocos"]) - remaining,
        "pendentes": remaining,
        "usados": list(usados),
        "concluidos_nesta_chamada": list(concluidos),
        "passagens_concluidas": len(context["sucessos"]),
        "falhas": list(falhas),
    }
