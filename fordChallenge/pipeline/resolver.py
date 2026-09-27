"""Passo 0 do pipeline: resolver a versão pedida na linha vigente.

É o primeiro passo de propósito. A lição 4 do gabarito é que **versões saem de linha**:
a Toyota não vende Hilux GR-Sport na linha 2026, e um sistema que extrai atributos sem
checar isso primeiro entrega uma ficha impecável de um carro que não existe mais no
catálogo — o pior tipo de erro, porque parece certo.

Três respostas possíveis (`docs/05`):

* `encontrada` — uma versão da linha bate com o pedido;
* `ambigua` — mais de uma bate igualmente bem (o pedido foi vago demais);
* `versao_inexistente` — nenhuma bate, e devolvemos a linha vigente como alternativa.

O match usa `rapidfuzz.token_set_ratio ≥ 85` sobre nomes normalizados (minúsculas, sem
acento, sem `at/mt/4x4`, que não distinguem versão). Um pedido parcial casa com o nome
completo — "Raptor 4x4" resolve para "Raptor 3.0 V6 Bi-turbo 4WD AT" — porque o vendedor
digita o apelido, não o nome de catálogo.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Literal

from rapidfuzz import fuzz

from pipeline import matching
from pipeline.connectors import (
    Connector,
    ResultadoLinha,
    VersionInfo,
    conector_de,
    marca_canonica,
)
from pipeline.connectors.base import normalizar_versao

log = logging.getLogger(__name__)

#: Limiar do `token_set_ratio` para considerar que o pedido casa com uma versão.
LIMIAR_MATCH = 85.0

StatusResolucao = Literal["encontrada", "ambigua", "versao_inexistente"]


@dataclass(frozen=True)
class Candidato:
    versao: VersionInfo
    score: float
    #: o nome normalizado do candidato é **idêntico** ao pedido normalizado
    exato: bool = False


@dataclass
class Resolution:
    """Resposta do Passo 0, pronta para ir ao `meta.version_resolution` da ficha."""

    status: StatusResolucao
    marca: str
    modelo: str
    versao_consultada: str
    matched_version: str | None = None
    alternatives: tuple[str, ...] = ()
    score: float = 0.0
    mensagem: str = ""
    fipe_last_year: int | None = None
    sources: tuple[str, ...] = ()
    lineup: tuple[VersionInfo, ...] = ()
    bloqueadas: tuple[str, ...] = ()
    nota_da_linha: str = ""
    pendencias: tuple[str, ...] = field(default_factory=tuple)

    @property
    def versao_resolvida(self) -> VersionInfo | None:
        if not self.matched_version:
            return None
        return next(
            (v for v in self.lineup if v.nome_exato == self.matched_version),
            None,
        )

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "matched_version": self.matched_version,
            "alternatives": list(self.alternatives),
            "score": round(self.score, 2),
            "mensagem": self.mensagem,
            "fipe_last_year": self.fipe_last_year,
            "sources": list(self.sources),
            "bloqueadas": list(self.bloqueadas),
            "pendencias": list(self.pendencias),
        }


def _candidatos(pedido: str, linha: ResultadoLinha) -> tuple[list[Candidato], bool]:
    """`(candidatos elegíveis, houve empate)` — a regra vive em :mod:`pipeline.matching`."""
    alvo = normalizar_versao(pedido)
    resultado = matching.avaliar(alvo, [normalizar_versao(v.nome_exato) for v in linha.versoes])
    if resultado.vencedor is not None:
        m = resultado.vencedor
        return [Candidato(linha.versoes[m.indice], m.score, m.exato)], False
    if resultado.empatados:
        return (
            [Candidato(linha.versoes[m.indice], m.score, m.exato) for m in resultado.empatados],
            True,
        )
    return [], False


def _ordenados_por_similaridade(pedido: str, linha: ResultadoLinha) -> list[Candidato]:
    """Toda a linha vigente ordenada por similaridade — as alternativas a oferecer."""
    alvo = normalizar_versao(pedido)
    todos = [
        Candidato(
            versao=v, score=float(fuzz.token_set_ratio(alvo, normalizar_versao(v.nome_exato)))
        )
        for v in linha.versoes
    ]
    todos.sort(key=lambda c: (-c.score, c.versao.nome_exato))
    return todos


def _data_por_extenso(iso: str) -> str:
    """`2026-09-01` vira `01/09/2026`. Texto que não é data volta como veio."""
    achado = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2}).*", iso.strip())
    return f"{achado[3]}/{achado[2]}/{achado[1]}" if achado else iso.strip()


def _mensagem_inexistente(
    marca: str,
    modelo: str,
    versao: str,
    alternativas: tuple[str, ...],
    *,
    coletado_em: str = "",
) -> str:
    """A mensagem é lida por humano na tela e no eval; o texto é contrato.

    `gabarito_v1.json` exige que ela contenha "não está na linha vigente" e o nome da
    versão equivalente sugerida — é o que o caso negativo verifica.

    **Esta função é a fronteira de linguagem.** Até 12/09/2026 ela recebia a `nota` da
    linha e a colava no fim como "Observação da coleta: …". A nota é escrita para quem
    mantém o pipeline, e num dos casos dizia, na tela de quem vende picape, "é o caso
    negativo do resolvedor. Preços não constam na página salva (status pendente_coleta no
    gabarito v1)". No ramo da exceção era pior: a mensagem do erro ia inteira.

    O que entra aqui é o que um vendedor precisa: a versão não está na linha, quais estão,
    e de quando é essa lista. A nota e o erro continuam em `Resolution.nota_da_linha`,
    para quem investiga — é a mesma separação que `web/src/lib/erros.ts` já faz com o HTTP:
    esta camada **traduz**, não repassa.
    """
    partes = [
        f'A versão "{versao}" não está na linha vigente de {marca} {modelo}.',
    ]
    if alternativas:
        partes.append("Versões na linha: " + ", ".join(alternativas) + ".")
    else:
        partes.append("Nenhuma versão da linha vigente foi obtida.")
    partes.append("Não encontrado não é o mesmo que não existe: confira a fonte e a data.")
    # A proveniência não some junto com a nota: trocar um defeito de linguagem por um
    # defeito de transparência seria pior num produto cuja promessa é "evidência com data".
    if coletado_em:
        partes.append(f"Esta lista foi consultada em {_data_por_extenso(coletado_em)}.")
    return " ".join(partes)


def resolve(
    marca: str,
    modelo: str,
    versao: str,
    *,
    connector: Connector | None = None,
    limiar: float = LIMIAR_MATCH,
) -> Resolution:
    """Resolve marca+modelo+versão contra a linha vigente.

    >>> r = resolve("Toyota", "Hilux", "GR-Sport")   # em REPLAY_MODE=1
    >>> r.status
    'versao_inexistente'
    >>> "SRX Plus AT" in r.alternatives
    True
    """
    conector = connector or conector_de(marca)
    # O nome canônico da marca quando conhecemos; o que o usuário digitou quando não.
    # Nunca o `marca` do conector genérico — dizer "linha vigente de generico Toro" é
    # ruído na tela de quem consultou "Fiat Toro".
    marca_exibida = marca_canonica(marca) or marca

    try:
        linha = conector.lineup(modelo)
    except Exception as exc:
        log.warning("resolver.linha_indisponivel", extra={"marca": marca, "erro": str(exc)})
        return Resolution(
            status="versao_inexistente",
            marca=marca_exibida,
            modelo=modelo,
            versao_consultada=versao,
            mensagem=_mensagem_inexistente(marca_exibida, modelo, versao, ()),
            nota_da_linha=str(exc),
            pendencias=("linha vigente indisponível: a fonte não pôde ser lida",),
        )

    candidatos, empate = _candidatos(versao, linha)
    fontes = tuple(dict.fromkeys([linha.url, *(v.url for v in linha.versoes if v.url)]))
    pendencias: tuple[str, ...] = ("fipe_last_year depende do conector FIPE da WP-13",)

    base = {
        "marca": marca_exibida,
        "modelo": modelo,
        "versao_consultada": versao,
        "lineup": tuple(linha.versoes),
        "sources": tuple(u for u in fontes if u),
        "bloqueadas": tuple(linha.bloqueadas),
        "nota_da_linha": linha.nota,
        "pendencias": pendencias,
    }

    if empate:
        alternativas = tuple(c.versao.nome_exato for c in candidatos)
        return Resolution(
            status="ambigua",
            alternatives=alternativas,
            score=candidatos[0].score,
            mensagem=(
                f'"{versao}" casa igualmente com {len(candidatos)} versões de '
                f"{marca_exibida} {modelo}: " + ", ".join(alternativas) + ". "
                "Escolha uma para seguir — o sistema não escolhe em silêncio."
            ),
            **base,
        )

    melhor = candidatos[0] if candidatos else None
    if melhor is None or melhor.score < limiar:
        # Alternativas = a linha vigente inteira, da mais parecida para a menos. É o que
        # transforma "não achei" em algo acionável: o vendedor vê o que existe.
        alternativas = tuple(
            c.versao.nome_exato for c in _ordenados_por_similaridade(versao, linha)
        )
        return Resolution(
            status="versao_inexistente",
            alternatives=alternativas,
            score=melhor.score if melhor else 0.0,
            mensagem=_mensagem_inexistente(
                marca_exibida, modelo, versao, alternativas, coletado_em=linha.captured_at
            ),
            **base,
        )

    if melhor.exato:
        return Resolution(
            status="encontrada",
            matched_version=melhor.versao.nome_exato,
            alternatives=(),
            score=melhor.score,
            mensagem=(
                f'"{versao}" corresponde exatamente à versão "{melhor.versao.nome_exato}" '
                f"da linha vigente (fonte: {linha.url or 'linha vigente'})."
            ),
            **base,
        )

    return Resolution(
        status="encontrada",
        matched_version=melhor.versao.nome_exato,
        alternatives=tuple(
            c.versao.nome_exato
            for c in _ordenados_por_similaridade(versao, linha)
            if c.versao.nome_exato != melhor.versao.nome_exato and c.score >= 60
        ),
        score=melhor.score,
        mensagem=(
            f'"{versao}" resolvida para "{melhor.versao.nome_exato}" '
            f"(similaridade {melhor.score:.0f}/100, fonte: {linha.url or 'linha vigente'})."
        ),
        **base,
    )


def linha_vigente(marca: str, modelo: str) -> ResultadoLinha:
    """Atalho para obter a linha vigente sem resolver versão nenhuma."""
    return conector_de(marca).lineup(modelo)


# ------------------------------------------------------------------------ persistência
def registrar_linha_vigente(marca: str, modelo: str, linha: ResultadoLinha) -> int:
    """Grava a linha vigente em `versions` (`in_lineup`, `lineup_checked_at`).

    Importa o banco **tardiamente** e devolve 0 sem erro quando a camada de dados não
    está disponível: o resolvedor tem de funcionar em teste de unidade e em replay sem
    banco nenhum. Quem precisa de persistência garantida chama e confere o retorno.
    """
    try:
        import datetime as dt

        from api.app.db import session_scope
        from api.app.repositories import brands, versions
    except ImportError:  # pragma: no cover - só quando a WP-03 não está no ambiente
        log.info("resolver.persistencia_indisponivel", extra={"marca": marca})
        return 0

    gravadas = 0
    agora = dt.datetime.now(dt.UTC)
    with session_scope() as sessao:
        registro_marca = brands.upsert(sessao, nome=marca)
        registro_modelo = brands.upsert_modelo(sessao, brand_id=registro_marca.id, nome=modelo)
        for v in linha.versoes:
            versions.upsert(
                sessao,
                model_id=registro_modelo.id,
                nome_exato=v.nome_exato,
                ano_modelo=v.ano_modelo,
                in_lineup=True,
                lineup_checked_at=agora,
            )
            gravadas += 1
    return gravadas


def main(*, marca: str, modelo: str, versao: str) -> int:
    """`specradar resolve <marca> <modelo> <versao>`."""
    import json

    resolucao = resolve(marca, modelo, versao)
    print(json.dumps(resolucao.to_dict(), ensure_ascii=False, indent=2))
    print()
    print(resolucao.mensagem)
    return 0 if resolucao.status == "encontrada" else 1
