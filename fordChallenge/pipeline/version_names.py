"""O nome canônico de uma versão — a regra, num lugar só.

`versions.nome_exato` é o que o rótulo `marca + modelo + nome_exato` mostra na tela. Quando
o nome repete o modelo, sai **"Chevrolet S10 S10 High Country"**; quando o mesmo veículo é
cadastrado com e sem o qualificador de carroceria, o catálogo ganha **duas linhas** e os
seletores oferecem duas opções para um carro só — uma delas sem ficha nenhuma.

A regra aqui é deliberadamente **estreita**, e a razão é assimétrica: não fundir duas
linhas custa uma opção repetida no seletor; fundir demais **apaga uma versão que existe**,
junto com a ficha dela. Só duas coisas saem do nome:

1. o **modelo repetido no começo** (`"S10 High Country"` → `"High Country"`);
2. o **qualificador de carroceria que é o padrão do segmento** e por isso não distingue
   nada (`"SRX Plus AT (Cabine Dupla)"` → `"SRX Plus AT"`). `"(Cabine Simples)"` fica:
   essa distingue.

Aliases adicionais só entram **um a um, com prova**. A página oficial da Ranger Raptor
2026 usa `"Raptor 4WD AT"` no título antigo e `"Raptor 3.0 V6 Bi-turbo 4WD AT"` no corpo;
esse par explícito é seguro. Não existe regra genérica de subconjunto de tokens, pois ela
fundiria `"SRX AT"` com `"SRX Plus AT"`, versões realmente diferentes.
"""

from __future__ import annotations

import re

from pipeline.ontology import normalize

#: Qualificadores entre parênteses que descrevem a carroceria **padrão** do segmento.
#:
#: Numa picape de topo, cabine dupla é o que se vende; escrever isso no nome não separa
#: nada de nada. O critério para entrar nesta lista é esse e só esse: o termo tem de ser
#: redundante, não distintivo. `cabine simples` fica de fora de propósito.
QUALIFICADORES_REDUNDANTES: frozenset[str] = frozenset(
    {
        "cabine dupla",
        "cab dupla",
        "cab. dupla",
        "cd",
        "4 portas",
        "quatro portas",
    }
)

_PARENTESES = re.compile(r"\(([^)]*)\)")

#: Aliases de versão comprovados por uma fonte que mostra os dois nomes para o mesmo
#: veículo. A chave inclui o modelo para nunca transformar coincidência de nome entre
#: linhas diferentes em merge. A evidência do par abaixo está no snapshot oficial
#: `ford_site_versao/page.md`: título curto e nome completo no corpo da mesma página.
ALIASES_COMPROVADOS: dict[tuple[str, str], str] = {
    ("ranger", "raptor 4wd at"): "Raptor 3.0 V6 Bi-turbo 4WD AT",
}


def _tokens(texto: str) -> list[str]:
    return [t for t in normalize(texto).split(" ") if t]


def _sem_qualificador_redundante(nome: str) -> str:
    """Tira os parênteses cujo conteúdo é redundante; deixa os que distinguem."""

    def decidir(achado: re.Match[str]) -> str:
        dentro = normalize(achado.group(1)).strip()
        return " " if dentro in QUALIFICADORES_REDUNDANTES else achado.group(0)

    return _PARENTESES.sub(decidir, nome)


def _sem_prefixo_do_modelo(modelo: str, nome: str) -> str:
    """Tira o nome do modelo quando ele abre o nome da versão, **token a token**.

    Token a token e não `startswith`: `"S10X Sport"` começa com a letra sequência de
    `"S10"` e não é uma S10 — arrancar por prefixo de texto inventaria a versão `"X Sport"`.
    """
    tokens_modelo = _tokens(modelo)
    if not tokens_modelo:
        return nome
    palavras = nome.split()
    normalizadas = [normalize(p) for p in palavras]
    if normalizadas[: len(tokens_modelo)] != tokens_modelo:
        return nome
    return " ".join(palavras[len(tokens_modelo) :])


def nome_canonico_de_versao(modelo: str, nome: str) -> str:
    """O `nome_exato` como deve ficar no catálogo e na tela.

    Nunca devolve vazio: uma versão sem nome é um registro que nenhuma tela mostra e
    nenhum resolvedor casa. Se as duas regras esvaziassem o nome, ele volta inteiro.
    """
    bruto = re.sub(r"\s+", " ", str(nome or "")).strip()
    if not bruto:
        return bruto
    limpo = re.sub(r"\s+", " ", _sem_qualificador_redundante(bruto)).strip()
    limpo = _sem_prefixo_do_modelo(modelo, limpo).strip()
    alias = ALIASES_COMPROVADOS.get((normalize(modelo), normalize(limpo)))
    if alias:
        return alias
    return limpo or bruto


def chave_de_versao(modelo: str, nome: str) -> str:
    """A chave que decide se duas linhas são a mesma versão. Normalizada, para comparar."""
    return normalize(nome_canonico_de_versao(modelo, nome))
