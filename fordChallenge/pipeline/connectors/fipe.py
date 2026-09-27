"""Conector FIPE (tier 2) e coleta de preço oficial (tier 1, com rebaixamento).

Duas coisas diferentes, no mesmo módulo porque as duas respondem "quanto custa":

* **FIPE** é o valor de referência de mercado, com **mês de referência** — e a referência
  é parte do dado, não um detalhe: "R$ 452.540" sem dizer "FIPE de setembro/2026" é um
  número sem validade. Toda consulta registra a referência.
* **Preço oficial** é o "a partir de" da montadora. Quando o site não publica preço por
  versão, o valor cai para imprensa (tier 3) com **confiança ≤ 0,60** e uma nota dizendo
  de onde veio. É o caso real da Amarok: o site não exibe preço por versão, e o gabarito
  registra `verificado_tier3` com o valor da Autoesporte.

Em replay, a FIPE vem do **snapshot salvo** da página de referência, parseado de verdade.
Ao vivo, da API comunitária (`FIPE_BASE_URL`), que muda de host de vez em quando — daí a
URL vir de env. O limite de 500 requisições/dia é respeitado com cache diário.

O catálogo pode fornecer `codigo_fipe` como pista de navegação. A publicação desse
campo exige o código literal em uma resposta ou página cuja identidade corresponda
ao veículo; metadado de catálogo, sozinho, não conta como prova nem acerto medido.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import NamedTuple

from pipeline import matching
from pipeline.connectors.base import normalizar_versao
from pipeline.units import parse_price

#: API comunitária. Muda de host de vez em quando (`specs/WP-13.md`).
FIPE_BASE_URL_PADRAO = "https://parallelum.com.br/fipe/api/v1"
#: Teto de requisições por dia da API comunitária.
LIMITE_DIARIO = 500
#: A FIPE é tier 2 por **tipo de fonte** (`docs/05`), qualquer que seja o documento
#: em que o valor foi lido.
TIER_FIPE = 2
#: Onde vive o contador diário de requisições. Em `data/`, que o `.gitignore` ignora.
CACHE_FIPE = Path(__file__).resolve().parents[2] / "data" / "cache" / "fipe"
#: Formato do código FIPE. Validar antes de montar URL evita gastar requisição com lixo.
_CODIGO_FIPE = re.compile(r"\d{6}-\d")
#: O que a FIPE usa no lugar do ano-modelo para veículo **zero-quilômetro**.
ANO_ZERO_KM = 32000

MESES = {
    "janeiro": 1,
    "fevereiro": 2,
    "marco": 3,
    "março": 3,
    "abril": 4,
    "maio": 5,
    "junho": 6,
    "julho": 7,
    "agosto": 8,
    "setembro": 9,
    "outubro": 10,
    "novembro": 11,
    "dezembro": 12,
}

_CODIGO = re.compile(r"C[óo]digo\s+FIPE:?\s*(?P<codigo>\d{6}-\d)", re.IGNORECASE)
#: O mês é capturado como **qualquer palavra** e validado depois contra `MESES`. Uma
#: classe de caracteres restrita simplesmente não casaria num mês inesperado, e a página
#: passaria como "sem referência" em vez de dizer que o mês é que estava estranho — falha
#: silenciosa no lugar de falha explicada.
_REFERENCIA = re.compile(
    r"Refer[êe]ncia\s+FIPE:?\s*(?P<mes>[^\W\d_]+)\s*(?:de\s*)?(?P<ano>\d{4})",
    re.IGNORECASE | re.UNICODE,
)
_PRECO = re.compile(r"Pre[çc]o:?\s*R\$\s*(?P<valor>[\d.]+(?:,\d{2})?)", re.IGNORECASE)
_ANO_COMBUSTIVEL = re.compile(r"Ano:?\s*(?P<ano>\d{4})\s*(?P<combustivel>\w+)?", re.IGNORECASE)
_MODELO_FIPE = re.compile(r"^#\s*Tabela FIPE\s+(?P<modelo>.+?):\s*R\$", re.MULTILINE)


class FipeIndisponivel(RuntimeError):
    """Não há como consultar a FIPE: sem snapshot em replay, sem rede ao vivo."""


def base_url() -> str:
    return os.environ.get("FIPE_BASE_URL", FIPE_BASE_URL_PADRAO).rstrip("/")


def referencia_iso(mes: str, ano: str | int) -> str:
    """`("Setembro", 2026)` → `"2026-09"`. A referência é parte do dado."""
    numero = MESES.get(str(mes).strip().lower())
    if numero is None:
        raise ValueError(f"mês de referência FIPE desconhecido: {mes!r}")
    return f"{int(ano):04d}-{numero:02d}"


@dataclass
class ConsultaFipe:
    """Uma consulta FIPE, com a referência mensal sempre presente."""

    codigo: str = ""
    preco_brl: int | None = None
    referencia: str = ""
    """`AAAA-MM`. Sem isso o preço não tem validade."""
    ano_modelo: int | None = None
    combustivel: str = ""
    zero_km: bool = False
    """A FIPE respondeu pelo registro de **zero-quilômetro** (`AnoModelo` 32000). O preço
    vale; o ano-modelo, não — e por isso `ano_modelo` fica vazio em vez de dizer 32000."""
    modelo_fipe: str = ""
    marca_fipe: str = ""
    url: str = ""
    origem: str = ""
    tier: int = TIER_FIPE
    motivo: str = ""
    source_id: str = ""
    """Snapshot de onde o valor foi lido, para o grounding ser reconferível."""
    quote_preco: str = ""
    """Trecho **verbatim** que contém o preço. Uma frase composta por nós groundearia
    contra um texto que nós mesmos escrevemos, o que não é evidência de nada."""
    quote_referencia: str = ""
    """Trecho verbatim que contém a referência mensal. É outro campo, com outra
    evidência: preço e referência raramente estão na mesma linha da página."""
    source_text: str = ""
    quote_codigo: str = ""

    @property
    def ok(self) -> bool:
        return self.preco_brl is not None and bool(self.referencia)

    def to_dict(self) -> dict:
        return {
            "codigo": self.codigo,
            "preco_brl": self.preco_brl,
            "referencia": self.referencia,
            "ano_modelo": self.ano_modelo,
            "combustivel": self.combustivel,
            "zero_km": self.zero_km,
            "modelo_fipe": self.modelo_fipe,
            "marca_fipe": self.marca_fipe,
            "url": self.url,
            "origem": self.origem,
            "tier": self.tier,
            "motivo": self.motivo,
            "source_id": self.source_id,
            "quote_preco": self.quote_preco,
            "quote_referencia": self.quote_referencia,
            "quote_codigo": self.quote_codigo,
        }


# ------------------------------------------------------- parse da página salva
#: O snapshot é a resposta da API, e não a página de referência? A marca é o nome do
#: campo, que a página em português nunca escreve assim.
_RESPOSTA_DE_API = re.compile(r'"CodigoFipe"\s*:\s*"?\d{6}-\d', re.IGNORECASE)


def _objeto_json_em(texto: str) -> str:
    """O primeiro objeto JSON completo dentro do texto, ou o texto como veio."""
    abre = texto.find("{")
    fecha = texto.rfind("}")
    return texto[abre : fecha + 1] if 0 <= abre < fecha else texto


def parse_pagina_fipe(texto: str, *, url: str = "") -> ConsultaFipe:
    """Lê o snapshot FIPE salvo — a página de referência **ou** a resposta da API.

    A página traz um bloco estruturado — `Código FIPE:`, `Ano:`, `Referência FIPE:`,
    `Preço:` — e é dele que os quatro campos saem. Nada é inferido do título.

    Quando o snapshot é o **JSON da API** (coleta de 10/09/2026), o parse é o da API: o
    corpo escreve `"CodigoFipe":"002215-2"`, que o regex de página, feito para
    `Código FIPE: 002215-2`, não reconhece. Sem esta bifurcação, o snapshot novo existia
    no disco e `find_code` respondia "sem página FIPE salva" — e `preco_fipe_brl` ficava
    `nao_encontrado` com o valor gravado logo ali.
    """
    if _RESPOSTA_DE_API.search(texto):
        # O snapshot é um `page.md`: cabeçalho, URL, `---`, e **depois** o corpo. O
        # `json.loads` do arquivo inteiro falha na primeira linha, e o motivo que saía
        # era "resposta da API FIPE não é JSON" — mensagem correta sobre a pergunta
        # errada. O que se parseia é o objeto; o texto salvo continua sendo o arquivo,
        # e é nele que o grounding procura a citação.
        consulta = parse_resposta_api(_objeto_json_em(texto), url=url)
        consulta.origem = "snapshot da resposta da API FIPE"
        return consulta
    consulta = ConsultaFipe(
        url=url, origem="snapshot da página de referência FIPE", source_text=texto
    )

    achado = _CODIGO.search(texto)
    if achado:
        consulta.codigo = achado.group("codigo")
        consulta.quote_codigo = achado.group(0).strip()

    achado = _REFERENCIA.search(texto)
    if achado:
        try:
            consulta.referencia = referencia_iso(achado.group("mes"), achado.group("ano"))
            consulta.quote_referencia = achado.group(0).strip()
        except ValueError as exc:
            consulta.motivo = str(exc)

    achado = _PRECO.search(texto)
    if achado:
        consulta.preco_brl = parse_price(achado.group("valor"))
        consulta.quote_preco = achado.group(0).strip()

    achado = _ANO_COMBUSTIVEL.search(texto)
    if achado:
        consulta.ano_modelo = int(achado.group("ano"))
        consulta.combustivel = (achado.group("combustivel") or "").lower()

    achado = _MODELO_FIPE.search(texto)
    if achado:
        consulta.modelo_fipe = achado.group("modelo").strip()

    if not consulta.ok and not consulta.motivo:
        faltando = [
            nome
            for nome, valor in (("preço", consulta.preco_brl), ("referência", consulta.referencia))
            if not valor
        ]
        consulta.motivo = f"página FIPE sem {' e sem '.join(faltando)}"
    return consulta


def consultar_em_replay(version_id: str) -> ConsultaFipe:
    """Consulta a FIPE a partir dos snapshots salvos da versão."""
    from pipeline.store import fontes_de, snapshots_de

    for snap in snapshots_de(version_id):
        if snap.tipo == "fipe" and snap.texto:
            # Tier do tipo de fonte, não do documento — ver `TIER_FIPE`.
            return parse_pagina_fipe(snap.texto, url=snap.url)

    # Sem página salva: a fonte consta como consultada, e o motivo diz o que falta.
    fipes = [f for f in fontes_de(version_id) if f.tipo == "fipe"]
    if fipes:
        return ConsultaFipe(
            url=fipes[0].url,
            origem="fonte registrada, sem texto salvo",
            motivo=(
                f"a fonte FIPE consta como consultada com status {fipes[0].status!r}, "
                "mas nenhum texto foi salvo — não há o que parsear em replay"
            ),
        )
    return ConsultaFipe(motivo=f"nenhuma fonte FIPE registrada para {version_id}")


# --------------------------------------------------------------- preço por código
def _dia_de_hoje() -> str:
    from datetime import date

    return date.today().isoformat()


def _caminho_do_contador(dia: str) -> Path:
    return CACHE_FIPE / f"requisicoes_{dia}.json"


def requisicoes_do_dia(dia: str | None = None) -> int:
    """Quantas requisições à API FIPE já saíram hoje, contando execuções anteriores.

    O teto de 500/dia é da API, não do processo: um contador em memória zeraria a cada
    `specradar run` e o limite viraria decorativo. Daí o contador viver em disco, com o
    dia no nome do arquivo.
    """
    caminho = _caminho_do_contador(dia or _dia_de_hoje())
    if not caminho.exists():
        return 0
    try:
        return int(json.loads(caminho.read_text(encoding="utf-8")).get("total", 0))
    except (ValueError, OSError):
        return 0


def _registra_requisicao(dia: str) -> None:
    CACHE_FIPE.mkdir(parents=True, exist_ok=True)
    caminho = _caminho_do_contador(dia)
    total = requisicoes_do_dia(dia) + 1
    caminho.write_text(json.dumps({"dia": dia, "total": total}), encoding="utf-8")


def _consulta_de_snapshot(codigo: str, ano: int | None) -> ConsultaFipe | None:
    """Procura o preço deste código nos snapshots salvos — página antes de registro.

    Duas passadas, e a ordem é a proveniência. A **captura da página** de referência
    (`tipo="fipe"`) vale mais que o **registro de evidência**, que guarda só o trecho
    verbatim e a URL de uma página que a coleta original não salvou em HTML
    (`scripts/build_fixtures.py` marca cada um dos dois no `meta.json`). É a mesma
    prioridade da D-33.

    O registro é aceito porque o trecho registrado — *"Referência FIPE: Setembro 2026;
    Preço: R$ 452.540,00"* — é texto coletado de verdade, vindo de `gabarito/raw/`, e sem
    ele campos legítimos ficariam sem fonte em replay. Não é circularidade: o gabarito
    **resposta** é `gabarito_v1.json`, e nada aqui o lê. Mas a origem viaja com o valor,
    porque tratar registro como captura de página seria mentir sobre a proveniência.

    O código FIPE tem de estar **no texto** nas duas passadas: é o que impede uma página
    qualquer de ser lida como fonte FIPE.
    """
    from pipeline.store import snapshots_de, versoes_disponiveis

    def tenta(so_pagina: bool) -> ConsultaFipe | None:
        for version_id in versoes_disponiveis():
            for snap in snapshots_de(version_id):
                if not snap.texto or (snap.tipo == "fipe") != so_pagina:
                    continue
                # Na captura, o código sai do bloco `Código FIPE:`. No registro ele vem
                # escrito à mão ("consultada; código 003506-8; referência Setembro 2026"),
                # então o que se exige é o código **literal** no texto — seis dígitos, um
                # hífen e um dígito é específico o suficiente para servir de guarda.
                consulta = parse_pagina_fipe(snap.texto, url=snap.url)
                if consulta.codigo != codigo and not (
                    not so_pagina and codigo in snap.texto and not consulta.codigo
                ):
                    continue
                # Ano pedido tem de ser **declarado** pela fonte. Aceitar
                # `ano_modelo=None` como "serve para qualquer ano" fazia o pedido de 2019
                # cair no registro (que não diz o ano) e voltar com o preço de 2026.
                # Fonte que não afirma o ano não confirma o ano.
                if ano is not None and consulta.ano_modelo != ano:
                    continue
                consulta.codigo = codigo
                consulta.source_id = snap.source_id
                # O tier **não** vem do documento. FIPE é tier 2 pelo tipo de fonte
                # (`docs/05`), e o `meta.tier` do registro descreve o registro — o do
                # Raptor é 1. Herdá-lo inflaria a confiança de um valor de mercado com o
                # tier de outra coisa, e para cima, que é o lado que engana.
                consulta.tier = TIER_FIPE
                if not so_pagina:
                    consulta.origem = (
                        f"{snap.tipo} ({snap.source_id}): trecho registrado na coleta, "
                        "não captura da página de referência"
                    )
                    if not consulta.ok:
                        consulta.motivo = (
                            f"o registro de {snap.source_id} nomeia o código {codigo}, mas não "
                            "traz o preço com a referência mensal; a página FIPE não foi salva. "
                            "Consultar a API ou salvar a página; não inferir"
                        )
                return consulta
        return None

    return tenta(so_pagina=True) or tenta(so_pagina=False)


def price(
    codigo: str,
    ano: int | None = None,
    *,
    marca: str = "",
    modelo: str = "",
) -> ConsultaFipe:
    """Preço FIPE de um código, **sempre** com a referência mensal.

    Em replay sai do snapshot salvo da página de referência; ao vivo, da API comunitária,
    com o cache diário de `pipeline.fetch.http` na frente (a URL inclui o dia, então uma
    segunda consulta no mesmo dia não gasta requisição) e o teto de
    `LIMITE_DIARIO` requisições contado em disco.

    `marca` e `modelo` são **dicas de navegação**, não a resposta: a API comunitária não
    tem rota por código FIPE (medido em 10/09/2026: `/carros/veiculos/003506-8` devolve
    `404 Cannot GET`), e o caminho real é marca → modelo → ano. O código pedido continua
    sendo o critério: se o objeto que voltar trouxer outro `CodigoFipe`, a consulta é
    **recusada**. Sem as dicas seriam ~90 requisições de varredura, e a API tem teto.

    Nunca levanta por indisponibilidade: devolve `ConsultaFipe` com `ok=False` e o motivo.
    Preço sem referência não é preço, e é por isso que `ok` exige as duas coisas.
    """
    if not _CODIGO_FIPE.fullmatch(codigo.strip()):
        return ConsultaFipe(
            codigo=codigo, motivo=f"código FIPE fora do formato NNNNNN-N: {codigo!r}"
        )
    codigo = codigo.strip()

    consulta = _consulta_de_snapshot(codigo, ano)
    if consulta is not None:
        return consulta

    from pipeline.fetch import http

    if http.modo_replay():
        return ConsultaFipe(
            codigo=codigo,
            origem="replay",
            motivo=(
                f"nenhum snapshot salvo traz a página FIPE do código {codigo}"
                + (f" para o ano {ano}" if ano else "")
                + " — em REPLAY_MODE=1 não se cai na rede"
            ),
        )

    dia = _dia_de_hoje()
    if requisicoes_do_dia(dia) >= LIMITE_DIARIO:
        return ConsultaFipe(
            codigo=codigo,
            origem="limite diário",
            motivo=(
                f"teto de {LIMITE_DIARIO} requisições/dia da API FIPE já alcançado em {dia}; "
                "a consulta não foi feita"
            ),
        )

    return _price_ao_vivo(codigo, ano, dia, marca=marca, modelo=modelo)


# ------------------------------------------------- navegação na API comunitária
#: Como a API comunitária grafa as marcas que o projeto usa. O nome do gabarito
#: ("Volkswagen", "Chevrolet") não é o nome da lista ("VW - VolksWagen", "GM - Chevrolet").
ALIAS_DE_MARCA_NA_API = {
    "volkswagen": "vw - volkswagen",
    "vw": "vw - volkswagen",
    "chevrolet": "gm - chevrolet",
    "gm": "gm - chevrolet",
}
#: Quantos modelos candidatos abrir antes de desistir. Cada um custa 2 requisições.
MAX_CANDIDATOS = 6


def _get_json(caminho: str, dia: str) -> tuple[object | None, str, str]:
    """`GET` na API comunitária com o contador diário. Devolve `(dados, corpo, motivo)`."""
    from pipeline.fetch import http

    url = f"{base_url()}{caminho}"
    resultado = http.fetch(url)
    if not resultado.de_cache:
        _registra_requisicao(dia)
    if not resultado.ok:
        return None, "", f"{resultado.status} — {resultado.motivo}"
    try:
        return json.loads(resultado.texto), resultado.texto, ""
    except ValueError as exc:
        return None, resultado.texto, f"resposta não é JSON: {exc}"


def _codigo_da_marca(marca: str, dia: str) -> tuple[str, str]:
    """`("Ford", ...)` → `("22", "")`. Segundo item é o motivo, quando não achou."""
    alvo = normalizar_versao(ALIAS_DE_MARCA_NA_API.get(marca.strip().lower(), marca))
    dados, _, motivo = _get_json("/carros/marcas", dia)
    if dados is None:
        return "", f"lista de marcas da API FIPE indisponível: {motivo}"
    if not isinstance(dados, list):
        return "", "lista de marcas da API FIPE não é uma lista"
    for item in dados:
        if normalizar_versao(str(item.get("nome", ""))) == alvo:
            return str(item.get("codigo", "")), ""
    return "", f"marca {marca!r} não está na lista da API FIPE"


def _modelos_candidatos(codigo_marca: str, modelo: str, dia: str) -> tuple[list[dict], str]:
    """Modelos da marca ordenados por cobertura dos tokens de `modelo`.

    Duas decisões, as duas por defeito medido em 10/09/2026:

    * **cobertura com tolerância a typo** (`pipeline.matching`) em vez de interseção
      exata: a FIPE grafa a S10 High Country como `"S10 P-Up H.Country 2.8 4x4 CD
      Dies.Aut."`, e `"country" ∩ "h.country"` é vazio para a interseção e 87,5 para o
      `ratio` — com interseção exata a S10 não era encontrada e o campo ficava vazio;
    * **portão pelo primeiro token** (o nome do modelo): sem ele, `"S10 High Country"`
      trazia `"Silverado High Country"` e `"TRAILBLAZER High Country"` na frente, e as
      requisições eram gastas com o veículo errado.
    """
    dados, _, motivo = _get_json(f"/carros/marcas/{codigo_marca}/modelos", dia)
    if dados is None or not isinstance(dados, dict):
        return [], f"lista de modelos da API FIPE indisponível: {motivo}"
    lista = dados.get("modelos") or []
    alvo = normalizar_versao(modelo).split()
    if not alvo:
        return [], "sem nome de modelo para procurar na API FIPE"
    nome_do_modelo = alvo[0]
    pontuados = []
    for item in lista:
        tokens = normalizar_versao(str(item.get("nome", ""))).split()
        if not matching.cobertura([nome_do_modelo], tokens):
            continue
        pontuados.append((matching.cobertura(alvo, tokens), str(item.get("nome", "")), item))
    pontuados.sort(key=lambda p: (-p[0], p[1]))
    return [item for _, _, item in pontuados[:MAX_CANDIDATOS]], ""


def _price_ao_vivo(
    codigo: str, ano: int | None, dia: str, *, marca: str = "", modelo: str = ""
) -> ConsultaFipe:
    """Navega marca → modelo → ano até achar o **código pedido**. Ver :func:`price`."""
    if not marca or not modelo:
        return ConsultaFipe(
            codigo=codigo,
            origem="API FIPE",
            motivo=(
                "a API comunitária não tem rota por código FIPE; a navegação precisa de "
                "marca e modelo, e nenhum dos dois foi informado"
            ),
        )

    codigo_marca, motivo = _codigo_da_marca(marca, dia)
    if not codigo_marca:
        return ConsultaFipe(codigo=codigo, origem="API FIPE", motivo=motivo)

    candidatos, motivo = _modelos_candidatos(codigo_marca, modelo, dia)
    if not candidatos:
        return ConsultaFipe(
            codigo=codigo,
            origem="API FIPE",
            motivo=motivo or f"nenhum modelo da API FIPE parece {modelo!r}",
        )

    tentados: list[str] = []
    for item in candidatos:
        codigo_modelo = str(item.get("codigo", ""))
        caminho = f"/carros/marcas/{codigo_marca}/modelos/{codigo_modelo}/anos"
        anos, _, motivo = _get_json(caminho, dia)
        if not isinstance(anos, list) or not anos:
            continue
        escolhidos = [a for a in anos if ano and str(a.get("nome", "")).startswith(str(ano))]
        # Sem o ano pedido, o zero-quilômetro ("32000") é a entrada certa para um
        # ano-modelo que a FIPE ainda não abriu — e é ela que a montadora vende hoje.
        if not escolhidos:
            escolhidos = [a for a in anos if str(a.get("codigo", "")).startswith("32000")]
        if not escolhidos:
            escolhidos = anos[:1]
        for escolha in escolhidos[:2]:
            dados, corpo, motivo = _get_json(f"{caminho}/{escolha.get('codigo')}", dia)
            if not isinstance(dados, dict):
                continue
            achado = str(dados.get("CodigoFipe") or "").strip()
            tentados.append(f"{item.get('nome')} [{achado}]")
            if achado == codigo:
                return parse_resposta_api(
                    corpo,
                    codigo=codigo,
                    url=f"{base_url()}{caminho}/{escolha.get('codigo')}",
                )
    return ConsultaFipe(
        codigo=codigo,
        origem="API FIPE",
        source_text=corpo,
        motivo=(
            f"nenhum modelo navegado devolveu o código {codigo}; "
            f"conferidos: {', '.join(tentados) or 'nenhum'}. "
            "Preço de outro código não é o preço desta versão"
        ),
    )


def parse_resposta_api(corpo: str, *, codigo: str = "", url: str = "") -> ConsultaFipe:
    """Lê o JSON da API comunitária. Referência ausente reprova a consulta.

    A API devolve `MesReferencia` como texto em português ("setembro de 2026"), e é dele
    que sai o `AAAA-MM`. Se o mês vier com nome desconhecido, o motivo diz isso em vez de
    devolver um preço sem validade.

    **As duas citações saem do corpo, recortadas dele.** Sem `quote_preco` e
    `quote_referencia`, `pipeline/run.py` descarta o campo com "consulta FIPE sem trecho
    verbatim" — foi assim que a S10 chegou ao eval sem `preco_fipe_brl` nem
    `fipe_referencia`, com a consulta funcionando. O corpo do JSON é o texto salvo do
    snapshot tier 2, e `"Valor": "R$ 294.378,00"` está literalmente nele: é evidência
    reconferível, não frase montada por nós.
    """
    try:
        dados = json.loads(corpo)
    except ValueError as exc:
        return ConsultaFipe(
            codigo=codigo, url=url, motivo=f"resposta da API FIPE não é JSON: {exc}"
        )
    if not isinstance(dados, dict):
        return ConsultaFipe(codigo=codigo, url=url, motivo="resposta da API FIPE não é um objeto")

    consulta = ConsultaFipe(
        codigo=str(dados.get("CodigoFipe") or codigo),
        url=url,
        origem="API FIPE",
        modelo_fipe=str(dados.get("Modelo") or ""),
        marca_fipe=str(dados.get("Marca") or ""),
        combustivel=str(dados.get("Combustivel") or "").lower(),
    )
    if dados.get("AnoModelo") is not None:
        with contextlib.suppress(TypeError, ValueError):
            bruto = int(dados["AnoModelo"])
            # `32000` é o código da FIPE para **zero-quilômetro**, não um ano. Gravá-lo
            # como ano-modelo poria "ano 32000" na ficha; deixá-lo passar em silêncio
            # poria um ano errado. Vira sinalizador, e o ano fica desconhecido.
            if bruto == ANO_ZERO_KM:
                consulta.zero_km = True
            else:
                consulta.ano_modelo = bruto
    if dados.get("Valor"):
        consulta.preco_brl = parse_price(str(dados["Valor"]).replace("R$", "").strip())

    referencia = str(dados.get("MesReferencia") or "").strip()
    achado = re.match(r"(?P<mes>[A-Za-zçÇãÃéÉ]+)\s*(?:de\s*)?(?P<ano>\d{4})", referencia)
    if achado:
        try:
            consulta.referencia = referencia_iso(achado.group("mes"), achado.group("ano"))
        except ValueError as exc:
            consulta.motivo = str(exc)
    elif referencia:
        consulta.motivo = f"mês de referência da API em formato desconhecido: {referencia!r}"

    consulta.quote_preco = _trecho_do_json(corpo, "Valor")
    consulta.quote_codigo = _trecho_do_json(corpo, "CodigoFipe")
    consulta.quote_referencia = _trecho_do_json(corpo, "MesReferencia")

    if not consulta.ok and not consulta.motivo:
        consulta.motivo = "resposta da API FIPE sem preço e sem referência"
    return consulta


_ABREVIACOES_DE_MODELO_FIPE = {
    "h.country": "high country",
    "ltd+": "limited plus",
    "ltd": "limited",
}
_TOKENS_TECNICOS_DE_VERSAO = {
    "bi",
    "turbo",
    "tb",
    "diesel",
    "dies",
    "dies.aut.",
    "cabine",
    "dupla",
    "cd",
}


def _tokens_de_modelo_fipe(texto: str) -> set[str]:
    normalizado = str(texto).lower()
    for abreviacao, extenso in _ABREVIACOES_DE_MODELO_FIPE.items():
        normalizado = re.sub(rf"(?<![\w.]){re.escape(abreviacao)}(?![\w])", extenso, normalizado)
    return set(normalizar_versao(normalizado).split())


def corresponde_ao_veiculo(
    consulta: ConsultaFipe,
    *,
    marca: str,
    modelo: str,
    versao: str,
    ano: int | None = None,
) -> tuple[bool, str]:
    """Confere a identidade antes de fundir uma resposta FIPE descoberta pela busca.

    O endpoint da FIPE descreve um único veículo, mas a busca pode ter devolvido a URL de
    uma versão vizinha. Marca, modelo, rótulo distintivo da versão e ano (quando o registro
    não é o especial de zero-quilômetro) precisam casar; potência ou motorização iguais não
    autorizam o merge de trims diferentes.
    """
    if not consulta.modelo_fipe:
        return False, "resposta FIPE sem nome do modelo/versao"

    tokens_fonte = _tokens_de_modelo_fipe(consulta.modelo_fipe)
    motores_alvo = set(re.findall(r"\b[1-8][.,]\d\b", versao))
    motores_fonte = set(re.findall(r"\b[1-8][.,]\d\b", consulta.modelo_fipe))
    if motores_alvo and motores_fonte and not motores_alvo & motores_fonte:
        return False, "motor FIPE incompatível com a configuração solicitada"
    tokens_modelo = _tokens_de_modelo_fipe(modelo)
    if not tokens_modelo or not tokens_modelo <= tokens_fonte:
        return False, f"modelo FIPE {consulta.modelo_fipe!r} nao corresponde a {modelo!r}"

    if consulta.marca_fipe:
        tokens_marca = _tokens_de_modelo_fipe(marca)
        tokens_marca_fonte = _tokens_de_modelo_fipe(consulta.marca_fipe)
        if tokens_marca and not tokens_marca & tokens_marca_fonte:
            return False, f"marca FIPE {consulta.marca_fipe!r} nao corresponde a {marca!r}"

    tokens_versao = _tokens_de_modelo_fipe(versao) - tokens_modelo
    distintivos = {
        token
        for token in tokens_versao
        if token not in _TOKENS_TECNICOS_DE_VERSAO and not re.fullmatch(r"v?\d+(?:\.\d+)?", token)
    }
    exigidos = distintivos or tokens_versao
    if exigidos and not exigidos <= tokens_fonte:
        return False, f"modelo FIPE {consulta.modelo_fipe!r} e de outra versao que {versao!r}"

    if ano is not None and consulta.ano_modelo != ano:
        return False, f"ano FIPE {consulta.ano_modelo!r} nao corresponde ao ano-modelo {ano}"
    return True, ""


def _trecho_do_json(corpo: str, chave: str) -> str:
    """O par `"chave": "valor"` **como está escrito** no corpo, ou vazio.

    Recortado do corpo, nunca remontado: o grounding confere a citação dentro do texto
    salvo, e um `json.dumps` nosso teria espaçamento diferente do original e falharia a
    conferência — ou, pior, passaria conferindo contra o que nós escrevemos.
    """
    achado = re.search(rf'"{re.escape(chave)}"\s*:\s*"[^"]*"', corpo) or re.search(
        rf'"{re.escape(chave)}"\s*:\s*[^,}}\s]+', corpo
    )
    return achado.group(0) if achado else ""


# --------------------------------------------------------------- código FIPE
@dataclass
class ResultadoCodigo:
    codigo: str | None = None
    origem: str = ""
    score: float = 0.0
    motivo: str = ""
    alternativas: tuple[str, ...] = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        return bool(self.codigo)


def find_code(
    marca: str,
    modelo: str,
    versao: str,
    *,
    modelos_fipe: dict[str, str] | None = None,
    catalogo: dict[str, str] | None = None,
    version_id: str = "",
) -> ResultadoCodigo:
    """Resolve o `codigo_fipe`, na ordem: catálogo → página salva → fuzzy na lista da API.

    `modelos_fipe` é `{nome do modelo na FIPE: código}` — a lista que a API devolve. O
    casamento usa a **mesma** regra do resolvedor de versão (`pipeline.matching`), porque
    o problema é o mesmo: "SRX Plus AT" tem de casar com
    "HILUX CD SRX PLUS 4X4 2.8 TDI Die. Aut." e não com "HILUX CD SRX 4X4...".
    """
    alvo = f"{modelo} {versao}"

    if catalogo:
        chave = normalizar_versao(alvo)
        for nome, codigo in catalogo.items():
            if normalizar_versao(nome) == chave:
                return ResultadoCodigo(codigo, "catálogo semeado do gabarito", 100.0)

    do_catalogo = _codigo_do_banco(marca, modelo, versao)
    if do_catalogo:
        return ResultadoCodigo(do_catalogo, "tabela versions (catálogo)", 100.0)

    if version_id:
        consulta = consultar_em_replay(version_id)
        if consulta.codigo:
            return ResultadoCodigo(consulta.codigo, "página FIPE salva", 100.0)

    if modelos_fipe:
        nomes = list(modelos_fipe)
        resultado = matching.avaliar(normalizar_versao(alvo), [normalizar_versao(n) for n in nomes])
        if resultado.vencedor is not None:
            nome = nomes[resultado.vencedor.indice]
            return ResultadoCodigo(
                modelos_fipe[nome],
                f"fuzzy na lista da FIPE ({nome})",
                resultado.vencedor.score,
            )
        if resultado.empatados:
            return ResultadoCodigo(
                None,
                "fuzzy na lista da FIPE",
                resultado.score,
                motivo=(
                    f'"{alvo}" casa igualmente com {len(resultado.empatados)} modelos da '
                    "FIPE; o sistema não escolhe em silêncio"
                ),
                alternativas=tuple(nomes[m.indice] for m in resultado.empatados),
            )
        return ResultadoCodigo(
            None,
            "fuzzy na lista da FIPE",
            resultado.score,
            motivo=f'nenhum modelo da FIPE casa com "{alvo}"',
        )

    return ResultadoCodigo(
        None,
        "",
        0.0,
        motivo=(
            "sem catálogo, sem página FIPE salva e sem a lista de modelos da API: "
            "código não resolvido (pendente_coleta)"
        ),
    )


def _codigo_do_banco(marca: str, modelo: str, versao: str) -> str | None:
    """Lê `versions.codigo_fipe`. Import tardio: funciona sem banco."""
    try:
        from sqlmodel import select

        from api.app.db import session_scope
        from api.app.models import Brand, VehicleModel, Version
    except ImportError:  # pragma: no cover - ambiente sem a WP-03
        return None
    try:
        with session_scope() as sessao:
            alvo = normalizar_versao(versao)
            consulta = (
                select(Version)
                .join(VehicleModel, VehicleModel.id == Version.model_id)
                .join(Brand, Brand.id == VehicleModel.brand_id)
            )
            for linha in sessao.exec(consulta):
                if linha.codigo_fipe and normalizar_versao(linha.nome_exato) == alvo:
                    return linha.codigo_fipe
    except Exception:  # pragma: no cover - banco ausente ou não migrado
        return None
    return None


# ----------------------------------------------------------------- preço oficial
@dataclass
class PrecoOficial:
    """Preço "a partir de", com o tier e a confiança que a fonte sustenta."""

    valor_brl: int | None = None
    quote: str = ""
    #: O texto que **ligou** este preço a esta versão. `quote` groundeia exato na fonte;
    #: `contexto` mostra por que o preço foi atribuído a esta versão e não a outra — a
    #: associação é uma inferência de layout, e quem revisa tem de poder vê-la.
    contexto: str = ""
    tier: int = 1
    confianca: float = 0.90
    fonte: str = ""
    data: str = ""
    nota: str = ""

    @property
    def ok(self) -> bool:
        return self.valor_brl is not None


#: Confiança máxima quando o preço vem de imprensa (`specs/WP-13.md`).
CONFIANCA_MAXIMA_T3 = 0.60

#: "A partir de R$ 348.790", "R$ 499.000", "Extreme (R$ 379.990)".
_PRECO_A_PARTIR = re.compile(
    r"(?:a\s+partir\s+de\s*)?R\$\s?(?P<valor>\d{1,3}(?:\.\d{3})+(?:,\d{2})?)(?P<marcador>\d)?",
    re.IGNORECASE,
)
#: Preço plausível de picape, para descartar número de rodapé.
FAIXA_PLAUSIVEL = (100_000, 1_500_000)
#: Caracteres procurados **antes** do preço à cata do nome da versão.
#:
#: Medido nas fontes salvas (`.tmp/probe_dist.py`), com a distância mínima em caracteres
#: entre cada preço e o nome da versão: os acertos exigem **8** (`"* **Extreme ("`) e
#: **12** (`"S10 High Country\nA partir de "` — o casamento começa em "A partir de", não
#: em "R$"); o falso positivo mais próximo exige **30**. A janela vive nessa folga.
#:
#: Erra-se para o lado pequeno de propósito. Janela curta demais transforma valor certo
#: em `pendente_coleta` — visível, e um humano coleta. Janela longa demais atribui preço
#: **errado** à versão, silenciosamente. Mesma assimetria da D-47.
JANELA_ANTES = 24
#: Cobertura de tokens da versão exigida na janela. Metade basta: a fonte escreve
#: "Extreme" onde o catálogo escreve "V6 Extreme".
COBERTURA_MINIMA_PRECO = 0.5
#: Escopos de página. `"linha"` cobre várias versões (chevrolet.com.br/picapes/s10);
#: `"versao"` é a página da própria versão (ford.com.br/.../raptor-4wd-at/).
ESCOPOS = ("linha", "versao")


def _janela_antes(texto: str, fim: int) -> str:
    """Os `JANELA_ANTES` caracteres imediatamente anteriores a `fim`, quebras incluídas."""
    return texto[max(0, fim - JANELA_ANTES) : fim]


def _lista_brl(valores) -> str:
    """`{379990, 389990}` → `"R$ 379.990, R$ 389.990"`, em ordem."""
    return ", ".join(f"R$ {v:,}".replace(",", ".") for v in sorted(valores))


def _linha_do_offset(texto: str, offset: int) -> str:
    """A linha que contém `offset`, para citar como evidência que groundeia exato."""
    inicio = texto.rfind("\n", 0, offset) + 1
    fim = texto.find("\n", offset)
    return texto[inicio : len(texto) if fim < 0 else fim].strip()[:200]


class PrecoBruto(NamedTuple):
    """Um preço achado na página, com os **dois** offsets que importam.

    São dois porque as pontas do casamento servem a coisas diferentes: `"a partir de"`
    entra no casamento mas não é nome de versão, e na Ford ele fica numa linha e o número
    na seguinte. `inicio` é onde a janela para trás começa (excluindo esse lead-in);
    `inicio_valor` é onde estão os dígitos, e é dele que sai a linha citada — evidência
    sem o número não é evidência.
    """

    valor: int
    inicio: int
    inicio_valor: int


def precos_plausiveis(texto: str) -> list[PrecoBruto]:
    """Todos os preços em R$ dentro da faixa plausível.

    A faixa descarta número de rodapé, de parcela e de financiamento.
    """
    achados: list[PrecoBruto] = []
    for achado in _PRECO_A_PARTIR.finditer(texto):
        valor = parse_price(achado.group("valor"))
        if FAIXA_PLAUSIVEL[0] <= valor <= FAIXA_PLAUSIVEL[1]:
            achados.append(PrecoBruto(valor, achado.start(), achado.start("valor")))
    return achados


def preco_oficial(
    texto: str,
    *,
    versao: str = "",
    tier: int = 1,
    fonte: str = "",
    data: str = "",
    escopo: str = "linha",
) -> PrecoOficial:
    """Extrai o preço "a partir de" **da versão pedida**, ou não devolve valor nenhum.

    O problema real: uma página de linha exibe **o preço de todas as versões**. A S10
    lista sete. Pegar "o preço da página" atribui à High Country o valor da Cabine
    Simples — um erro grande, silencioso e plausível.

    O que liga um preço a uma versão, nas fontes reais, é o nome **imediatamente antes**
    dele:

    * `"S10 High Country"` numa linha e `"A partir de R$ 348.790"` na seguinte;
    * `"* **Volkswagen Amarok Extreme** \\- R$ 379.990"`;
    * `"* **Extreme (R$ 379.990)** : itens da Highline + rodas de 20 polegadas"`.

    Daí a janela ser de **caracteres antes** do preço, não de linhas em volta. Uma janela
    de linhas simétrica erra num caso que existe de verdade na Autoesporte:
    `"* **Barretos 70 anos (R$ 389.990)** : itens da **Extreme** + capota"` — a versão
    pedida aparece na mesma linha, mas **depois** do preço, como descrição do que a
    edição limitada herda. O preço ali é da Barretos. Ler só para trás resolve isso pela
    estrutura da frase em português ("Versão — R$ X"), não por sorte de ordenação.

    A cobertura é a de `pipeline/matching.py`, e **meia** cobertura basta: o catálogo diz
    "V6 Extreme" onde a reportagem diz "Extreme".

    Sem o nome antes de nenhum preço — ou com o nome antes de **preços diferentes** — o
    resultado é **sem valor**, com a nota dizendo o que falta e quais valores competiam.
    Não há fallback para "o menor preço da página": o gabarito da Hilux é exatamente este
    caso e manda `pendente_coleta` — *"Site exibe apenas 'A partir de R$ 292.790,00' para
    a linha (versão de entrada). Coletar no configurador Toyota ou release; **não
    inferir**."* Preço errado num comparativo é pior que preço ausente.

    `escopo="versao"` é a exceção honesta: numa página que **é** da versão (a URL da
    Raptor), um único preço plausível é o preço dela, e exigir o nome do lado seria
    inventar um requisito que a fonte não tem. Mais de um preço numa página de versão
    volta a exigir o nome — aí a página não é tão específica quanto se disse.
    """
    if escopo not in ESCOPOS:
        raise ValueError(f"escopo deve ser um de {ESCOPOS}, não {escopo!r}")

    alvo = normalizar_versao(versao) if versao else ""
    tokens_alvo = alvo.split()
    achados = precos_plausiveis(texto)

    if not achados:
        return PrecoOficial(
            valor_brl=None,
            tier=tier,
            fonte=fonte,
            data=data,
            nota="a página não exibe preço em R$ numa faixa plausível para esta categoria",
        )

    def resultado(bruto: PrecoBruto, contexto: str) -> PrecoOficial:
        r = PrecoOficial(
            valor_brl=bruto.valor,
            quote=_linha_do_offset(texto, bruto.inicio_valor),
            contexto=contexto,
            tier=tier,
            confianca=0.90,
            fonte=fonte,
            data=data,
        )
        if tier >= 3:
            r.confianca = min(r.confianca, CONFIANCA_MAXIMA_T3)
            r.nota = (
                "preço de imprensa (tier 3): o site oficial não publica preço por versão. "
                f"Confiança limitada a {CONFIANCA_MAXIMA_T3:.2f}."
            )
        return r

    # A versão nomeada antes do preço — o caminho normal, e o único para página de linha.
    candidatos: list[tuple[float, PrecoBruto, str]] = []
    for bruto in achados:
        antes = _janela_antes(texto, bruto.inicio)
        cobertura = matching.cobertura(tokens_alvo, normalizar_versao(antes).split())
        if tokens_alvo and cobertura >= COBERTURA_MINIMA_PRECO:
            candidatos.append((cobertura, bruto, antes.strip()))

    if candidatos:
        melhor = max(c[0] for c in candidatos)
        empatados = [c for c in candidatos if c[0] == melhor]
        valores = {c[1].valor for c in empatados}
        if len(valores) > 1:
            # Menções de força igual e valores diferentes: a **página** não decide qual é
            # o preço desta versão. Escolher o menor seria decidir por sorte de ordenação,
            # e um preço errado num comparativo é pior que um preço ausente. Os valores
            # concorrentes vão na nota — divergência se expõe, não se resolve na surdina.
            return PrecoOficial(
                valor_brl=None,
                tier=tier,
                fonte=fonte,
                data=data,
                nota=(
                    f'a página nomeia a versão "{versao}" antes de {len(valores)} preços '
                    f"diferentes ({_lista_brl(valores)}); não há como saber qual é o dela. "
                    "Coletar em fonte que publique preço por versão; não inferir."
                ),
            )
        _, bruto, contexto = empatados[0]
        return resultado(bruto, contexto)

    # Página da própria versão com um preço só: a URL é a associação.
    #
    # "Um preço só" é **um valor distinto**, não uma ocorrência só. A página da Ranger
    # Limited escreve `R$ 346.900` duas vezes — no bloco do preço e no rodapé do
    # disclaimer —, e contar ocorrências fazia a página da própria versão ser recusada
    # por "ambiguidade" entre um número e ele mesmo. Dois valores **diferentes** numa
    # página de versão continuam exigindo o nome ao lado: aí a página não é tão
    # específica quanto a URL diz.
    valores_distintos = {a.valor for a in achados}
    if escopo == "versao" and len(valores_distintos) == 1:
        r = resultado(achados[0], "")
        repetido = (
            f" O valor aparece {len(achados)}× na página, sempre igual." if len(achados) > 1 else ""
        )
        r.nota = (
            "a associação vem do escopo da página (URL da própria versão), não do texto "
            "ao lado do preço." + repetido
        ) + (f" {r.nota}" if r.nota else "")
        return r

    quantos = (
        f"o único preço da página ({_lista_brl({achados[0].valor})}) não é atribuído"
        if len(achados) == 1
        else f"nenhum dos {len(achados)} preços da página é atribuído"
    )
    return PrecoOficial(
        valor_brl=None,
        tier=tier,
        fonte=fonte,
        data=data,
        nota=(
            f'{quantos} à versão "{versao}" pelo texto que o precede. '
            "Coletar em fonte que publique preço por versão; não inferir."
        ),
    )
