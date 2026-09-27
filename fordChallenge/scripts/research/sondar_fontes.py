"""Sondagem dos sites de ficha técnica candidatos a `pipeline/research/fontes.yaml`.

**Por que um script, e não escrever o YAML de cabeça.** Em 13/09/2026, tentando os doze sites
que o dono mapeou, desta mesma máquina: `carrosnaweb` respondeu 500 para dois user-agents;
`icarros/catalogo` devolveu 348 mil caracteres de HTML e três mil de texto (é montado por
JavaScript); `mobiauto` e `kbb` deram 404 nas URLs chutadas; `carro.info` e `fichasautomotivas`
não resolveram DNS. Um YAML escrito sem medir teria seis linhas erradas em doze.

O que se mede, por site e por veículo de prova:

1. **a busca acha a página?** — Tavily restrita ao domínio (`include_domains`);
2. **a página abre?** — `http.fetch` (o coletor educado); bloqueio ou texto curto escalam para o
   navegador (Crawl4AI + Chromium), como a pesquisa vai passar a fazer;
3. **tem ficha em tabela?** — linhas `rótulo⇥valor` depois de `html_para_texto`;
4. **quanto sai por regra, sem modelo?** — o fast-path sobre o texto, com `permitir_llm=False`;
5. **quais rótulos a regra não conhece?** — a lista que alimenta a Fase 2 (ontologia).

Custa buscas (1 crédito cada) e coleta; **zero chamadas de modelo**. Saída em
`reports/research/sondagem_fontes.md`, com a decisão sugerida por site.

    python scripts/research/sondar_fontes.py [--sem-navegador] [--dominio X ...]
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(dotenv_path=RAIZ / ".env", override=True)
os.environ["REPLAY_MODE"] = "0"
os.environ["LLM_FAKE"] = "1"  # a sondagem nunca chama o modelo

#: Os doze sites do dono, com a URL de exemplo que ele mandou quando havia uma.
SITES: dict[str, str] = {
    "carrosnaweb.com.br": "https://www.carrosnaweb.com.br/fichadetalhe.asp?codigo=32979",
    "carrosegaragem.com.br": "",
    "icarros.com.br": "",
    "kbb.com.br": "",
    "mobiauto.com.br": "",
    "noticiasautomotivas.com.br": "",
    "quatrorodas.abril.com.br": "",
    "motor1.uol.com.br": "",
    "autopapo.uol.com.br": "",
    "carro.info": "",
    "fichasautomotivas.com.br": "",
    "pbeveicular.inmetro.gov.br": "",
}

#: Dois veículos de prova: um bloqueado no site oficial (a S10) e um que o catálogo já tem.
VEICULOS = (
    ("Chevrolet", "S10", "High Country", 2026),
    ("Ford", "Ranger", "Raptor", 2026),
)

#: Abaixo disto o HTML "abriu" mas não trouxe página: é o sinal de JavaScript ou de bloqueio macio.
TEXTO_CURTO = 2_000


@dataclass
class Medida:
    site: str
    veiculo: str
    url: str = ""
    busca: str = ""
    coleta: str = ""
    caracteres: int = 0
    linhas_com_tab: int = 0
    campos_por_regra: int = 0
    campos: list[str] = field(default_factory=list)
    rotulos_desconhecidos: Counter = field(default_factory=Counter)
    segundos: float = 0.0
    erro: str = ""


def buscar(consulta: str, dominio: str, quantos: int = 3) -> list[dict]:
    """Tavily restrita a um domínio.

    Chamada direta porque `search.buscar` ainda não aceita lista de domínios — isso é a
    Fase 1; aqui a sondagem precisa do recurso antes de ele existir no pipeline.
    """
    import httpx

    chave = os.environ.get("SEARCH_API_KEY", "").strip()
    if not chave:
        raise RuntimeError("SEARCH_API_KEY vazia")
    resposta = httpx.post(
        "https://api.tavily.com/search",
        json={
            "api_key": chave,
            "query": consulta,
            "max_results": quantos,
            "search_depth": "basic",
            "include_answer": False,
            "include_domains": [dominio],
        },
        timeout=20.0,
        headers={"User-Agent": os.environ.get("SPECRADAR_USER_AGENT", "SpecRadar/0.1")},
    )
    resposta.raise_for_status()
    return resposta.json().get("results", [])


def coletar(url: str, *, usar_navegador: bool) -> tuple[str, str, str]:
    """Devolve `(texto, como, erro)`; `como` ∈ http | navegador | bloqueada | erro."""
    from pipeline.fetch import http
    from pipeline.parse.html import html_para_texto, parece_html

    texto, como, erro = "", "", ""
    try:
        r = http.fetch(url, timeout=20.0, tentativas=1)
        if r.bloqueado or r.status == "blocked":
            como, erro = "bloqueada", "403/CAPTCHA no fetch"
        else:
            texto = r.texto or ""
            texto = html_para_texto(texto) if parece_html(texto) else texto
            como = "http"
    except Exception as exc:
        como, erro = "erro", f"{type(exc).__name__}: {exc}"[:120]

    if usar_navegador and (como != "http" or len(texto) < TEXTO_CURTO):
        try:
            from pipeline.fetch import browser

            if browser.disponivel():
                rn = browser.fetch_browser(url)
                if rn.ok and (rn.markdown or rn.html):
                    bruto = rn.markdown or html_para_texto(rn.html)
                    if len(bruto) > len(texto):
                        texto, como, erro = bruto, "navegador", ""
                elif not texto:
                    erro = erro or f"navegador: {rn.status} {rn.motivo}"[:120]
        except Exception as exc:
            erro = erro or f"navegador: {type(exc).__name__}: {exc}"[:120]
    return texto, como, erro


def medir_regra(texto: str, marca: str, modelo: str, versao: str) -> tuple[list[str], Counter]:
    """Campos que o fast-path lê sem modelo, e os rótulos de tabela que ele não reconhece."""
    from pipeline.extract.fastpath import ROTULO_PARA_CAMPO
    from pipeline.extract.run import Documento, extrair_documento
    from pipeline.ontology import normalizar_rotulo
    from pipeline.research import gaps
    from pipeline.run import CAMPOS_DE_SERVICO

    alvo = set(gaps.campos_procuraveis()) - set(CAMPOS_DE_SERVICO)
    doc = Documento(texto=texto, source_id="sondagem", url="", tier=3)
    resultado = extrair_documento(
        doc, alvo, marca=marca, modelo_veiculo=modelo, versao=versao, permitir_llm=False
    )
    campos = sorted({c.campo for c in resultado.candidatos})

    desconhecidos: Counter = Counter()
    for linha in texto.splitlines():
        if "\t" not in linha:
            continue
        rotulo = linha.split("\t", 1)[0].strip()
        if not rotulo or len(rotulo) > 60:
            continue
        if normalizar_rotulo(rotulo) not in ROTULO_PARA_CAMPO:
            desconhecidos[rotulo] += 1
    return campos, desconhecidos


def sondar(site: str, marca: str, modelo: str, versao: str, ano: int, *, navegador: bool) -> Medida:
    veiculo = f"{marca} {modelo} {versao} {ano}"
    m = Medida(site=site, veiculo=veiculo)
    inicio = time.perf_counter()
    try:
        achados = buscar(f"{veiculo} ficha técnica", site)
    except Exception as exc:
        m.busca, m.erro = "erro", f"busca: {type(exc).__name__}: {exc}"[:120]
        m.segundos = time.perf_counter() - inicio
        return m
    candidatas = [a.get("url", "") for a in achados if a.get("url")]
    m.busca = f"{len(achados)} resultado(s)" if achados else "vazia"
    exemplo = SITES.get(site, "")
    if exemplo and exemplo not in candidatas:
        candidatas.append(exemplo)
    if not candidatas:
        m.segundos = time.perf_counter() - inicio
        return m

    # **Até três URLs, e fica a melhor.** A busca costuma devolver a *listagem* antes da
    # ficha — no `carrosnaweb`, `catalogo.asp?varnome=s10` vem na frente de
    # `fichadetalhe.asp?codigo=…`. Medir só a primeira reprovaria o site por engano.
    for url in candidatas[:3]:
        texto, como, erro = coletar(url, usar_navegador=navegador)
        campos: list[str] = []
        desconhecidos: Counter = Counter()
        if texto:
            campos, desconhecidos = medir_regra(texto, marca, modelo, versao)
        if len(campos) > m.campos_por_regra or (not m.url):
            m.url, m.coleta, m.erro = url, como, erro
            m.caracteres = len(texto)
            m.linhas_com_tab = sum(1 for linha in texto.splitlines() if "\t" in linha)
            m.campos, m.campos_por_regra = campos, len(campos)
            m.rotulos_desconhecidos = desconhecidos
        if m.campos_por_regra >= 12:  # já provou que é ficha; não gasta as outras
            break
    m.segundos = time.perf_counter() - inicio
    return m


def decidir(medidas: list[Medida]) -> tuple[str, str]:
    """A decisão sugerida para o site e o motivo, a partir das duas provas."""
    if all(m.busca in ("erro", "vazia") and not m.url for m in medidas):
        return "descartar", "a busca não devolve nada deste domínio (morto, ou sem ficha)"
    abriu = [
        m for m in medidas if m.coleta in ("http", "navegador") and m.caracteres >= TEXTO_CURTO
    ]
    if not abriu:
        return "descartar", "nenhuma página abriu com texto (bloqueio, JavaScript ou erro)"
    tabelas = max(m.linhas_com_tab for m in abriu)
    regra = max(m.campos_por_regra for m in abriu)
    navegador = any(m.coleta == "navegador" for m in abriu)
    tipo = "ficha" if tabelas >= 10 or regra >= 12 else "imprensa"
    motivo = f"{regra} campo(s) por regra, {tabelas} linha(s) rótulo⇥valor"
    if navegador:
        motivo += "; exige navegador"
    return tipo, motivo


def relatorio(medidas: dict[str, list[Medida]], navegador: bool) -> str:
    agora = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    linhas = [
        "# Sondagem dos sites de ficha técnica",
        "",
        f"Medido em {agora}, desta máquina, com navegador "
        f"{'ligado' if navegador else 'desligado'}. Veículos de prova: "
        f"{'; '.join(' '.join(map(str, v)) for v in VEICULOS)}. Zero chamadas de modelo.",
        "",
        "| site | decisão | motivo | busca | coleta | texto | pares | campos por regra | seg |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for site, ms in medidas.items():
        tipo, motivo = decidir(ms)
        for m in ms:
            linhas.append(
                f"| {site} | **{tipo}** | {motivo} | {m.busca} | {m.coleta or '—'}"
                f"{' (' + m.erro + ')' if m.erro else ''} | {m.caracteres} | {m.linhas_com_tab} | "
                f"{m.campos_por_regra} | {m.segundos:.0f} |"
            )
    linhas += ["", "## Campos lidos por regra, por site", ""]
    for site, ms in medidas.items():
        campos = sorted({c for m in ms for c in m.campos})
        linhas.append(f"- **{site}** ({len(campos)}): {', '.join(campos) or '—'}")
    linhas += ["", "## Rótulos de tabela que o fast-path não reconhece (Fase 2)", ""]
    todos: Counter = Counter()
    for ms in medidas.values():
        for m in ms:
            todos.update(m.rotulos_desconhecidos)
    for rotulo, n in todos.most_common(60):
        linhas.append(f"- `{rotulo}` ×{n}")
    linhas += ["", "## URLs que responderam", ""]
    for site, ms in medidas.items():
        for m in ms:
            if m.url:
                linhas.append(f"- {site} · {m.veiculo}: {m.url}")
    return "\n".join(linhas) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--sem-navegador", action="store_true")
    parser.add_argument("--dominio", action="append", help="sondar só este(s) domínio(s)")
    args = parser.parse_args()
    navegador = not args.sem_navegador
    sites = args.dominio or list(SITES)

    medidas: dict[str, list[Medida]] = {}
    for site in sites:
        medidas[site] = []
        for marca, modelo, versao, ano in VEICULOS:
            m = sondar(site, marca, modelo, versao, ano, navegador=navegador)
            medidas[site].append(m)
            print(
                f"{site:28} {m.veiculo[:26]:26} busca={m.busca:14} coleta={m.coleta or '—':10} "
                f"texto={m.caracteres:>7} tab={m.linhas_com_tab:>3} regra={m.campos_por_regra:>2} "
                f"{m.segundos:5.0f}s {m.erro}",
                flush=True,
            )
    destino = RAIZ / "reports" / "research" / "sondagem_fontes.md"
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(relatorio(medidas, navegador), encoding="utf-8", newline="\n")
    print(f"\nrelatório: {destino}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
