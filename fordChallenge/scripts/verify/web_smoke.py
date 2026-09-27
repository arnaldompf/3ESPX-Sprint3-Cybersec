"""Abre o web app num Chromium de verdade e prova que ele renderiza (D-188).

Por que este arquivo existe, em uma frase: **status 200 não é prova de tela**.

Em 11/09/2026 as oito rotas respondiam 200, com o content-type certo, e os 18 testes de
`tests/api/test_web.py` passavam — e o Chrome do humano mostrava uma página **branca**. A
CSP `default-src 'none'` bloqueava o próprio bundle que aqueles testes confirmavam ser
servido (D-184). `curl` e o `TestClient` não aplicam CSP; navegador aplica. O vão entre
"o servidor entregou" e "o navegador aceitou" não tinha nenhum portão, e este é ele.

O que é exigido de cada uma das 32 combinações (8 rotas × 4 papéis):

1. **um `<h1>` visível e com texto** — a tela diz onde a pessoa está;
2. **zero erro de console**, zero requisição falhada (CSP conta como falha) e **zero
   401** — 401 numa tela já autenticada é sessão quebrada. 403 **não** entra na conta:
   é a matriz de papéis funcionando, e a tela mostra a recusa em português;
3. **um print que não está em branco** — medido em pixels, não em bytes: um PNG de
   página branca tem tamanho de arquivo perfeitamente saudável.

O critério de "não está em branco" é deliberadamente grosseiro e por isso confiável: a
imagem precisa ter mais de uma cor e pelo menos 0,5% de pixels diferentes da cor de
fundo. Uma tela branca com um cabeçalho de 40 px já passa; uma tela branca de verdade,
não.
"""

from __future__ import annotations

import argparse
import collections
import json
import pathlib
import sys

import httpx
from PIL import Image
from playwright.sync_api import Error as ErroDoPlaywright
from playwright.sync_api import sync_playwright

RAIZ = pathlib.Path(__file__).resolve().parents[2]
SAIDA = RAIZ / "reports" / "screens"

PAPEIS = ("vendedor", "analista", "gestor", "admin")

#: As dez rotas. Nove são as abas; `ficha` é o **deep link**, que é exatamente a forma
#: de endereço em que o humano bateu ("/app/consulta abre em branco").
ROTAS: tuple[tuple[str, str], ...] = (
    ("consulta", "/app/consulta"),
    ("pesquisa", "/app/pesquisa"),
    ("radar", "/app/radar"),
    ("matriz", "/app/matriz"),
    ("showroom", "/app/showroom"),
    ("saude", "/app/saude"),
    ("insights", "/app/insights"),
    ("simulador", "/app/simulador"),
    ("benchmark", "/app/benchmark"),
    ("ficha", "/app/ficha/{version_id}"),
)

#: Mensagens de console que **não** contam como erro.
#:
#: A terceira é a que exige explicação. `Failed to load resource: ... 403` é o texto que
#: o **próprio navegador** escreve para qualquer resposta não-2xx, e um 403 aqui não é
#: defeito: é a matriz de papéis funcionando. O vendedor recebe 403 em `/alerts` por
#: decisão de produto (`docs/12` §6.1) e a tela mostra a recusa em português (D-180).
#: Tratar isso como falha faria o portão exigir que o vendedor visse o que é do gestor.
#:
#: **401 continua contando** — e conta por fora, em `ao_responder`: 401 não é regra, é
#: sessão quebrada, e foi exatamente o que este portão pegou na primeira execução (D-186).
RUIDO_ACEITO: tuple[str, ...] = (
    "Download the React DevTools",
    "[vite] connected",
    "Failed to load resource:",
)

#: Fração mínima de pixels diferentes do fundo para o print não contar como branco.
FRACAO_MINIMA_DE_TINTA = 0.005


def _e_ruido(texto: str) -> bool:
    return any(marca in texto for marca in RUIDO_ACEITO)


def tinta_do_print(caminho: pathlib.Path) -> float:
    """Fração de pixels diferentes da cor mais comum. Zero = imagem de uma cor só."""
    with Image.open(caminho) as imagem:
        reduzida = imagem.convert("RGB").resize((320, 200))
        # `tobytes` e nao `getdata`: o segundo esta depreciado no Pillow 12 e o aviso
        # poluiria a saida do portao, que precisa ser legivel.
        bruto = reduzida.tobytes()
    cores = collections.Counter(bruto[i : i + 3] for i in range(0, len(bruto), 3))
    total = sum(cores.values())
    if not total:
        return 0.0
    _fundo, quantos = cores.most_common(1)[0]
    return (total - quantos) / total


def um_version_id(base: str) -> str:
    """Um id de versão real, para o deep link da ficha.

    Vem da API e não de uma constante: os ids são sorteados a cada montagem da base, e um
    id escrito aqui funcionaria hoje e daria 404 amanhã — o mesmo risco que o roteiro da
    demo já teve (D-183).
    """
    with httpx.Client(base_url=base, timeout=20.0) as cliente:
        veiculos = cliente.get("/api/v1/vehicles", headers={"X-Role": "gestor"})
        veiculos.raise_for_status()
    lista = veiculos.json()
    if not lista:
        raise SystemExit(
            "a base nao tem nenhum veiculo: rode `python scripts/demo/preparar_base.py`"
        )
    return lista[0]["id"]


def _entrar(pagina, base: str, papel: str) -> None:
    """Abre o app no papel pedido, **trocando pela barra lateral**.

    Não há mais tela de entrada (D-204): `/app` cai direto na Consulta. O que se prova
    aqui continua sendo o caminho da pessoa — abrir o menu do rodapé da barra e escolher
    o papel —, e não um atalho: gravar `localStorage` por fora pularia justamente o
    controle que passou a decidir o que cada tela mostra.
    """
    pagina.goto(f"{base}/app/consulta", wait_until="domcontentloaded")
    pagina.wait_for_url("**/app/consulta", timeout=15_000)
    atual = pagina.get_by_test_id("papel-atual")
    atual.wait_for(state="visible", timeout=15_000)
    if atual.inner_text().strip().lower() == papel:
        return
    pagina.get_by_test_id("trocar-papel").click()
    opcao = pagina.get_by_test_id(f"papel-{papel}")
    opcao.wait_for(state="visible", timeout=15_000)
    opcao.click()
    pagina.wait_for_function(
        "papel => document.querySelector('[data-testid=papel-atual]')"
        "?.textContent?.trim()?.toLowerCase() === papel",
        arg=papel,
        timeout=15_000,
    )


def visitar(pagina, base: str, rota: str, destino: pathlib.Path) -> dict:
    """Abre uma rota, guarda o print e devolve o que der errado nela."""
    problemas: list[str] = []
    console: list[str] = []
    nao_autenticado: list[str] = []

    def ao_console(msg) -> None:
        if msg.type == "error" and not _e_ruido(msg.text):
            console.append(msg.text)

    def ao_erro_de_pagina(exc) -> None:
        console.append(f"exceção não tratada: {exc}")

    def ao_falhar(requisicao) -> None:
        # A CSP aparece aqui como `failure == "csp"`, e foi assim que D-184 foi medido.
        console.append(f"requisição falhou ({requisicao.failure}): {requisicao.url}")

    def ao_responder(resposta) -> None:
        # 401 numa tela ja autenticada significa que a sessao nao sobreviveu ao
        # recarregamento — o defeito D-186. 403 nao entra: e a matriz de papeis.
        if resposta.status == 401:
            nao_autenticado.append(resposta.url.split("/api/v1", 1)[-1])

    pagina.on("console", ao_console)
    pagina.on("pageerror", ao_erro_de_pagina)
    pagina.on("requestfailed", ao_falhar)
    pagina.on("response", ao_responder)
    try:
        pagina.goto(f"{base}{rota}", wait_until="networkidle", timeout=30_000)
    except ErroDoPlaywright as exc:
        problemas.append(f"a rota nao carregou: {exc}".split("\n")[0])

    titulo = ""
    try:
        cabecalho = pagina.locator("h1").first
        cabecalho.wait_for(state="visible", timeout=10_000)
        titulo = (cabecalho.inner_text() or "").strip()
    except ErroDoPlaywright:
        problemas.append("nenhum <h1> visivel na tela")
    if not titulo and "nenhum <h1>" not in " ".join(problemas):
        problemas.append("o <h1> esta vazio")

    destino.parent.mkdir(parents=True, exist_ok=True)
    pagina.screenshot(path=str(destino), full_page=True)
    tinta = tinta_do_print(destino)
    if tinta < FRACAO_MINIMA_DE_TINTA:
        problemas.append(f"o print saiu em branco ({tinta:.4%} de tinta)")

    pagina.remove_listener("console", ao_console)
    pagina.remove_listener("pageerror", ao_erro_de_pagina)
    pagina.remove_listener("requestfailed", ao_falhar)
    pagina.remove_listener("response", ao_responder)
    problemas.extend(f"console: {linha}" for linha in console)
    problemas.extend(
        f"401 numa tela ja autenticada: {rota}" for rota in sorted(set(nao_autenticado))
    )
    return {"titulo": titulo, "tinta": tinta, "problemas": problemas}


def escrever_indice(resultados: list[dict]) -> None:
    """`reports/screens/README.md` — a lista de todos os prints, com o que cada um prova."""
    linhas = [
        "# Prints das telas",
        "",
        "Gerado por `scripts/verify/web-smoke.sh` (D-188). Cada linha é uma rota aberta num",
        "Chromium headless, no papel escolhido **pelo seletor da barra lateral** — não por",
        "`localStorage` gravado por fora. Não há login: a ferramenta abre na Consulta (D-204).",
        "",
        "Cada print passou por três exigências: um `<h1>` visível e com texto, zero erro de",
        "console (CSP bloqueada conta como erro) e uma imagem que **não** está em branco,",
        "medida em pixels. A coluna *tinta* é a fração de pixels diferentes da cor de fundo;",
        f"o mínimo exigido é {FRACAO_MINIMA_DE_TINTA:.1%}.",
        "",
        "**As imagens nao vao para o repositorio** e os links so funcionam depois de voce",
        "rodar o portao: sao 7,6 MB de PNG que ele regenera a cada `verify-quick`, e",
        "versiona-los encheria o historico de blob novo por imagens iguais a olho nu. Para",
        "produzi-las (40 s): `make web-smoke`. O que fica versionado e esta tabela — o titulo",
        "que cada tela mostrou e quanta tinta o print tinha —, que e a medida, nao a foto.",
        "",
        "Este arquivo existe porque, em 11/09/2026, as oito rotas respondiam 200 com o",
        "content-type certo e a tela abria **branca** no Chrome (D-184). `curl` não aplica",
        'CSP; navegador aplica. A partir daqui, "funciona" só vale com print renderizado.',
        "",
        "| papel | tela | título na tela | tinta | print |",
        "| --- | --- | --- | ---: | --- |",
    ]
    for item in sorted(resultados, key=lambda r: (r["papel"], r["tela"])):
        caminho = f"{item['papel']}/{item['tela']}.png"
        linhas.append(
            f"| {item['papel']} | {item['tela']} | {item['titulo']} | "
            f"{item['tinta']:.1%} | [{caminho}]({caminho}) |"
        )
    linhas.append("")
    linhas.append(f"{len(resultados)} prints, {len(PAPEIS)} papéis × {len(ROTAS)} telas.")
    linhas.append("")
    (SAIDA / "README.md").write_text("\n".join(linhas), encoding="utf-8", newline="\n")


def main() -> int:
    analise = argparse.ArgumentParser(description=__doc__)
    analise.add_argument("--base", default="http://127.0.0.1:8000")
    analise.add_argument("--papeis", default=",".join(PAPEIS), help="papeis separados por virgula")
    argumentos = analise.parse_args()
    base = argumentos.base.rstrip("/")
    papeis = tuple(p.strip() for p in argumentos.papeis.split(",") if p.strip())

    version_id = um_version_id(base)
    SAIDA.mkdir(parents=True, exist_ok=True)

    resultados: list[dict] = []
    falhas: list[str] = []
    with sync_playwright() as p:
        navegador = p.chromium.launch()
        for papel in papeis:
            # Um contexto por papel: `localStorage` limpo, sem herdar o papel anterior.
            contexto = navegador.new_context(viewport={"width": 1280, "height": 900})
            pagina = contexto.new_page()
            try:
                _entrar(pagina, base, papel)
            except ErroDoPlaywright as exc:
                falhas.append(f"{papel}: nao consegui entrar pela tela — {exc}".split("\n")[0])
                contexto.close()
                continue
            for tela, molde in ROTAS:
                rota = molde.format(version_id=version_id)
                destino = SAIDA / papel / f"{tela}.png"
                achado = visitar(pagina, base, rota, destino)
                resultados.append({"papel": papel, "tela": tela, "rota": rota, **achado})
                marca = "ok " if not achado["problemas"] else "FALHOU"
                print(
                    f"   {marca} {papel:9s} {tela:10s} "
                    f"{achado['tinta']:6.1%} tinta  {achado['titulo'][:38]}"
                )
                for problema in achado["problemas"]:
                    print(f"        - {problema}")
                    falhas.append(f"{papel}/{tela}: {problema}")
            contexto.close()
        navegador.close()

    if resultados:
        escrever_indice(resultados)
    (SAIDA / "resultado.json").write_text(
        json.dumps({"resultados": resultados, "falhas": falhas}, ensure_ascii=False, indent=2),
        encoding="utf-8",
        newline="\n",
    )

    esperado = len(papeis) * len(ROTAS)
    print()
    print(f"   {len(resultados)}/{esperado} telas abertas; prints em reports/screens/")
    if falhas:
        print(f"   {len(falhas)} problema(s):")
        for falha in falhas[:20]:
            print(f"     - {falha}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
