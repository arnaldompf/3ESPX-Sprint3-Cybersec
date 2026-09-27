"""CarrosNaWeb (tier 3): ficha padronizada por versão + ano-modelo, para qualquer marca.

`https://www.carrosnaweb.com.br/fichadetalhe.asp?codigo=NNNNN` publica, no mesmo formato
para todos os veículos: rpm de potência, torque com rpm, número de marchas, 0-100 km/h,
suspensão, pneus, aro e preço. `robots.txt` permite `/fichadetalhe.asp` explicitamente
(bloqueia só `/resultnotas.asp`, `/opiniaovota.asp`, `/comparativovota.asp`).

**Nunca ler `potencia_cv` daqui.** O valor em cv é renderizado como imagem
(`campoImagem/imgValorN.asp`) — só o rpm é texto. `potencia_cv` já vem de fonte oficial
em todos os alvos conhecidos.

Formato real da página (conferido em snapshots de pesquisa ao vivo já salvos no repo,
ex. `data/snapshots/.../carrosnaweb_com_br_fichadetalhe_asp_codigo_49975.../page.md`):
tabela markdown **pipe-delimited**, uma versão só por página — não a grade multi-coluna
de `pipeline/parse/version_slicer.recortar`. `_celulas_da_tabela` monta a lista de
`Celula` direto do pipe-table, coluna=1, sem slicing (não há o que fatiar).

Descoberta do `codigo`: mapa estático em `pipeline/research/acervo.yaml` — o site exige
navegador (sem ele, a ficha responde 500) e a busca interna devolve a listagem antes da
ficha, então resolver por sitemap/busca não é viável sem baixar fichas às cegas.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from pipeline.extract import fastpath
from pipeline.extract.run import Candidato
from pipeline.identity import Applicability, VehicleTarget, assess, claim_rejection
from pipeline.parse.version_slicer import Celula

TIER = 3
SOURCE_ID = "carrosnaweb_ficha"

_ALLOWED_HOSTS = frozenset({"carrosnaweb.com.br", "www.carrosnaweb.com.br"})

#: Os campos que este conector tem permissão de responder. `potencia_cv` fica de fora de
#: propósito (é imagem), e os 4 modos também (o CarrosNaWeb não os publica — continuam
#: vindo só da montadora).
CAMPOS_ALVO: frozenset[str] = frozenset(
    {
        "torque_nm",
        "torque_rpm",
        "potencia_rpm",
        "numero_marchas",
        "aceleracao_0_100_s",
        "suspensao_dianteira",
        "suspensao_traseira",
        "amortecedores",
        "pneus_medida",
        "rodas_aro_pol",
        "preco_sugerido_brl",
    }
)

#: `potencia_rpm` sem cv e `aceleracao_0_100_s` pelo rótulo vivem em `fastpath.py`
#: (compartilhado com o pipeline clássico) desde que se descobriu que `pipeline/run.py`
#: não despacha para nenhum conector — só fast-path genérico. Mantê-las só aqui deixava
#: `potencia_rpm` fora de `make eval`/reprocessamento em lote.

#: Sintaxe de link/imagem markdown: `[texto](url "título")` ou `![alt](url)`. O grupo 1
#: é o que sobra visível quando a página vira texto — é isso que o `evidence_quote`
#: precisa casar, não a URL.
_LINK_MD = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")


def _limpar_celula(bruto: str) -> str:
    texto = _LINK_MD.sub(lambda m: m.group(1), bruto)
    return re.sub(r"[ \t]+", " ", texto).strip()


def _texto_legivel(texto: str) -> str:
    """Tira a sintaxe de link/imagem markdown do texto **inteiro**, preservando quebras
    de linha. Sem isto, um rótulo como "Câmbio  |  [Automático](url) de 10 marchas"
    produz valor limpo "Automático de 10 marchas" que não é mais substring literal do
    texto salvo — e o `evidence_quote` verbatim deixaria de casar (grounding falharia em
    silêncio). Rodar a limpeza no texto inteiro, uma vez, mantém texto e valor no mesmo
    espaço: tudo que vira quote sai **deste** texto, que é o que fica em `source_text`.
    """
    return _LINK_MD.sub(lambda m: m.group(1), texto)


def _url_valida(url: str) -> bool:
    """`https`, host na allowlist, sem credencial, porta padrão, `/fichadetalhe.asp`
    com só `codigo=<dígitos>` na query. Barra por construção `/resultcompara.asp` e as
    rotas que o robots.txt proíbe — nenhuma delas casa `/fichadetalhe.asp` literal."""
    try:
        p = urlsplit(url)
    except ValueError:
        return False
    if (
        p.scheme != "https"
        or p.hostname not in _ALLOWED_HOSTS
        or p.username is not None
        or p.password is not None
        or p.port not in (None, 443)
        or p.path.lower() != "/fichadetalhe.asp"
    ):
        return False
    pares = [par.split("=", 1) for par in p.query.split("&") if par]
    if len(pares) != 1 or pares[0][0] != "codigo":
        return False
    return pares[0][1].isdigit()


def _celulas_da_tabela(texto: str, versao: str) -> list[Celula]:
    """`Celula`s direto das linhas `| rótulo | valor | rótulo2 | valor2 |` do pipe-table.

    Ficha do CarrosNaWeb é de **uma** versão só — não há coluna para fatiar, e por isso
    `coluna=1`/`alcance=(1,)` são fixos: o `Celula` existe aqui só para reaproveitar
    `fastpath.extrair_de_celulas` (campo de texto livre e `CAMPO_EXTRA_DA_CELULA`), não
    para resolver ambiguidade entre versões.
    """
    celulas: list[Celula] = []
    for numero, linha in enumerate(texto.splitlines()):
        bruta = linha.strip()
        if not bruta.startswith("|"):
            continue
        partes = [_limpar_celula(p) for p in bruta.strip("|").split("|")]
        while partes and partes[-1] == "":
            partes.pop()
        if len(partes) < 2:
            continue
        for i in range(0, len(partes) - 1, 2):
            rotulo, valor = partes[i], partes[i + 1]
            if not rotulo or not valor or valor in {"-", "–", "—"}:
                continue
            celulas.append(
                Celula(
                    rotulo=rotulo,
                    valor=valor,
                    coluna=1,
                    alcance=(1,),
                    versoes_cobertas=(versao,),
                    pagina=0,
                    linha=numero,
                )
            )
    return celulas


def identidade_ok(texto: str, url: str, target: VehicleTarget) -> bool:
    """Três camadas obrigatórias — é o que fecha o incidente MY2025→MY2026 que o projeto
    já teve com esta mesma fonte (`docs/13`, item Fase 2 do plano de 18/18):

    (a) `assess(...).status is COMPATIBLE`;
    (b) `target.ano_modelo` precisa estar em `observed["anos_modelo"]` — sem isso
        `assess` devolve `INSUFFICIENT`, que passaria pela camada (a) sozinha;
    (c) casamento **literal** de `Ano` + o ano-modelo nos primeiros 3 KB — a página real
        escreve só "Ano  2026", não "Ano modelo 2026" (conferido ao vivo em 2026-09-15).
    """
    if not target.ano_modelo:
        return False
    avaliacao = assess(target, texto, url=url)
    if avaliacao.status is not Applicability.COMPATIBLE:
        return False
    if target.ano_modelo not in avaliacao.observed.get("anos_modelo", []):
        return False
    janela = texto[:3000]
    return bool(re.search(rf"\bAno\b[^\n]*\b{target.ano_modelo}\b", janela))


def candidatos(
    texto: str,
    url: str,
    target: VehicleTarget,
    source_id: str = "",
    captured_at: str = "",
) -> list[Candidato]:
    """Roda o fast-path existente sobre o texto (inline) e sobre as células do pipe-table
    (rótulo/valor); descarta o que `identity.claim_rejection` recusar. Nunca sai vazio
    por engano quando a URL ou a identidade não batem — ficha errada não vira valor.
    """
    if not _url_valida(url) or not identidade_ok(texto, url, target):
        return []

    legivel = _texto_legivel(texto)
    achados = list(fastpath.extrair_de_texto(legivel, campos=CAMPOS_ALVO))
    achados += fastpath.extrair_potencia_rpm_sem_cv(legivel, campos=CAMPOS_ALVO)
    achados += fastpath.extrair_aceleracao_0_100_rotulo(legivel, campos=CAMPOS_ALVO)
    celulas = _celulas_da_tabela(legivel, target.versao)
    achados += fastpath.extrair_de_celulas(celulas, campos=CAMPOS_ALVO, texto=legivel)

    resultado: list[Candidato] = []
    vistos: set[tuple[str, str, str]] = set()
    for achado in achados:
        if achado.campo not in CAMPOS_ALVO:
            continue
        chave = (achado.campo, achado.quote, repr(achado.valor))
        if chave in vistos:
            continue
        vistos.add(chave)
        if claim_rejection(target, achado.quote, source_text=legivel):
            continue
        resultado.append(
            Candidato(
                campo=achado.campo,
                valor=achado.valor,
                unidade=achado.unidade,
                valor_bruto=achado.valor_bruto,
                quote=achado.quote,
                origem=f"fastpath:carrosnaweb_{achado.regra}",
                source_id=source_id or SOURCE_ID,
                source_text=legivel,
                url=url,
                tier=TIER,
                captured_at=captured_at,
                de_celula=achado.de_celula,
                notas=achado.notas or "Ficha padronizada do CarrosNaWeb (tier 3).",
            )
        )
    return resultado


def supports(
    field: str, target: VehicleTarget, text: str, url: str, quote: str, value=None
) -> bool:
    """Reexecuta a extração e confere que `quote` (e opcionalmente `value`) sobrevivem —
    usado por `publication.choose`/`reconcile` para vincular a exceção de identidade ao
    valor específico, não à fonte inteira."""
    if not quote or quote not in _texto_legivel(text or ""):
        return False
    return any(
        c.campo == field and c.quote == quote and (value is None or c.valor == value)
        for c in candidatos(text, url, target)
    )
