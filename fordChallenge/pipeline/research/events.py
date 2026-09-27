"""Os eventos do run: o que a tela mostra **enquanto acontece**, e o que fica para auditar.

Dois usos, e é bom que sejam o mesmo objeto: o painel ao vivo da Consulta lê estes eventos
por SSE, e a auditoria posterior lê os mesmos, gravados. Se fossem dois formatos, a tela
mostraria uma coisa e o registro guardaria outra — e a promessa do produto é justamente que
o que se vê é o que aconteceu.

**O desenho é o do Simplicity, com um passo a mais.** Eles transmitem passos tipados
(`consulta → resultados → página lida`) e mostram a consulta **verbatim**, não uma
paráfrase — o que copiamos. O que falta lá, e que é o nosso produto, é o passo final:
`{campo, valor, status, evidence_quote, url, tier}`. Sem ele, a trilha prova que uma busca
aconteceu; com ele, prova de onde veio cada número.

**A URL descartada aparece, com o motivo.** É o oposto do instinto: mostrar só o que deu
certo faria a tela parecer mais limpa e a pesquisa, menos conferível. Uma fonte descartada
em silêncio é indistinguível de uma fonte que ninguém viu.
"""

from __future__ import annotations

import contextlib
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class Tipo(StrEnum):
    """Os passos de um run. A ordem aqui é a ordem em que eles acontecem."""

    INICIO = "inicio"
    RODADA = "rodada"
    CONSULTA = "consulta"
    RESULTADOS = "resultados"
    FONTE_ESCOLHIDA = "fonte_escolhida"
    FONTE_DESCARTADA = "fonte_descartada"
    BAIXANDO = "baixando"
    BAIXADA = "baixada"
    FONTE_BLOQUEADA = "fonte_bloqueada"
    LENDO = "lendo"
    MODELO = "modelo"
    """O modelo leu um documento: qual modelo, qual fonte, quantos campos, quanto custou."""
    ESPERA = "espera"
    """O trinco de vazão dormiu: quanto e por quê. Sem isto, a tela pareceria travada."""
    CAMPO = "campo"
    COBERTURA = "cobertura"
    LACUNA = "lacuna"
    AVISO = "aviso"
    FIM = "fim"


#: A etiqueta de cada tipo de evento, no vocabulário de `docs/13` §2.
#:
#: **FATO** é o que se observou acontecer (uma consulta foi feita, uma página foi baixada, um
#: campo saiu com trecho verbatim). **INFERÊNCIA** é o que o sistema decidiu por regra: o
#: tier de um domínio, o descarte de uma fonte, a escolha da próxima consulta. A separação
#: é a mesma da ficha, e pelo mesmo motivo — quem lê tem de saber o que é observação e o
#: que é leitura nossa.
ETIQUETA: dict[Tipo, str] = {
    Tipo.INICIO: "FATO",
    Tipo.RODADA: "FATO",
    Tipo.CONSULTA: "FATO",
    Tipo.RESULTADOS: "FATO",
    Tipo.FONTE_ESCOLHIDA: "INFERENCIA",
    Tipo.FONTE_DESCARTADA: "INFERENCIA",
    Tipo.BAIXANDO: "FATO",
    Tipo.BAIXADA: "FATO",
    Tipo.FONTE_BLOQUEADA: "FATO",
    Tipo.LENDO: "FATO",
    Tipo.MODELO: "FATO",
    Tipo.ESPERA: "FATO",
    Tipo.CAMPO: "FATO",
    Tipo.COBERTURA: "FATO",
    Tipo.LACUNA: "INFERENCIA",
    Tipo.AVISO: "INFERENCIA",
    Tipo.FIM: "FATO",
}


@dataclass
class Evento:
    """Um passo do run, com tudo o que a tela precisa para desenhá-lo.

    `texto` é a frase que a pessoa lê; `dados` é o que o desenvolvedor confere depois. Os
    dois viajam juntos porque separá-los faria a tela ter de reconstruir a frase — e duas
    reconstruções divergem.
    """

    tipo: Tipo
    texto: str
    dados: dict[str, Any] = field(default_factory=dict)
    rodada: int = 0
    decorrido: float = 0.0
    ordem: int = 0

    @property
    def etiqueta(self) -> str:
        return ETIQUETA.get(self.tipo, "INFERENCIA")

    def to_dict(self) -> dict[str, Any]:
        return {
            "ordem": self.ordem,
            "tipo": self.tipo.value,
            "texto": self.texto,
            "etiqueta": self.etiqueta,
            "rodada": self.rodada,
            "decorrido": self.decorrido,
            "dados": self.dados,
        }

    def sse(self) -> str:
        """O evento no formato do `text/event-stream`.

        `event:` com o tipo permite ao front escutar só o que lhe interessa; `data:` numa
        linha só porque JSON com quebra de linha quebra o protocolo — e um painel que
        engasga no meio da pesquisa é pior que um painel que não existe.
        """
        corpo = json.dumps(self.to_dict(), ensure_ascii=False)
        return f"event: {self.tipo.value}\ndata: {corpo}\n\n"


@dataclass
class Trilha:
    """Os eventos de um run, em ordem, com o relógio de cada um.

    Guarda tudo em memória durante a pesquisa **e avisa quem quiser ouvir a cada passo**
    (`ao_registrar`). O worker usa o aviso para gravar cada evento em `research_events`
    na hora em que acontece — até 13/09/2026 a trilha só era gravada no fim, e a tela
    "ao vivo" via a pesquisa pronta. O observador que levantar é engolido: a pesquisa não
    pode morrer porque quem a assiste tropeçou.
    """

    eventos: list[Evento] = field(default_factory=list)
    rodada: int = 0
    _relogio: Any = None
    ao_registrar: Callable[[Evento], None] | None = None

    def registrar(self, tipo: Tipo, texto: str, /, **dados: Any) -> Evento:
        """Um passo novo na trilha. `tipo` e `texto` são **posicionais**, e a barra importa.

        Sem ela, um evento que queira um dado chamado `tipo` — e a fonte escolhida quer,
        para dizer se a página é ficha ou matéria — colide com o parâmetro e o Python
        recusa a chamada com "got multiple values for argument 'tipo'". A barra reserva os
        dois nomes para os dados do evento, que são livres por natureza.
        """
        evento = Evento(
            tipo=tipo,
            texto=texto,
            dados=dados,
            rodada=self.rodada,
            decorrido=round(self._relogio() if self._relogio else 0.0, 2),
            ordem=len(self.eventos),
        )
        self.eventos.append(evento)
        if self.ao_registrar is not None:
            with contextlib.suppress(Exception):
                self.ao_registrar(evento)
        return evento

    def de_tipo(self, tipo: Tipo) -> list[Evento]:
        return [e for e in self.eventos if e.tipo is tipo]

    @property
    def consultas(self) -> list[str]:
        return [e.dados.get("consulta", "") for e in self.de_tipo(Tipo.CONSULTA)]

    @property
    def baixadas(self) -> list[str]:
        return [e.dados.get("url", "") for e in self.de_tipo(Tipo.BAIXADA)]

    @property
    def bloqueadas(self) -> list[str]:
        return [e.dados.get("url", "") for e in self.de_tipo(Tipo.FONTE_BLOQUEADA)]

    def to_list(self) -> list[dict[str, Any]]:
        return [e.to_dict() for e in self.eventos]


__all__ = ["ETIQUETA", "Evento", "Tipo", "Trilha"]
