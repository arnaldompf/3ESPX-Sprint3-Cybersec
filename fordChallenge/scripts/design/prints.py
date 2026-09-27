"""Prints de todas as telas, em 1440 e 390, para o ciclo de autocorreção visual.

É o `web_smoke.py` com outro propósito. O portão mede se a tela **abre** (h1 visível, zero
erro de console, print não-branco) a 1280 px; este mede se ela **está pronta**, nas duas
larguras que o `010_DESIGN.md` §8 nomeia — a de trabalho (1440) e a de bolso (390) — e
guarda as imagens em `<saida>/<papel>/<tela>-<largura>.png`, que é o material do teste
"parece 2012?" e do `ANTES_DEPOIS.md`.

Ele troca de papel **pelo seletor da barra lateral**, como o portão: o que se quer ver é a
tela que a pessoa vê, e não uma montada por fora.

    python scripts/design/prints.py --base http://127.0.0.1:8012
    python scripts/design/prints.py --papeis analista --telas consulta,radar
    python scripts/design/prints.py --saida reports/screens/v2   # a rodada anterior
"""

from __future__ import annotations

import argparse
import json
import pathlib

import httpx
from PIL import Image
from playwright.sync_api import Error as ErroDoPlaywright
from playwright.sync_api import sync_playwright

RAIZ = pathlib.Path(__file__).resolve().parents[2]
#: A rodada atual de acabamento. `--saida` muda, para comparar com a anterior sem
#: sobrescrevê-la: `reports/screens/v2/` é o "antes" do `ANTES_DEPOIS.md`.
SAIDA_PADRAO = RAIZ / "reports" / "screens" / "v3"

PAPEIS = ("vendedor", "analista", "gestor", "admin")

#: As nove telas, na ordem do passeio guiado. `ficha` é o deep link.
#:
#: `login` saiu da lista em 12/09/2026: a tela deixou de existir (D-204) e o endereço
#: redireciona para a Consulta — um print dela seria um print da Consulta com outro nome.
ROTAS: dict[str, str] = {
    "consulta": "/app/consulta",
    "ficha": "/app/ficha/{version_id}",
    "radar": "/app/radar",
    "matriz": "/app/matriz",
    "showroom": "/app/showroom",
    "saude": "/app/saude",
    "insights": "/app/insights",
    "simulador": "/app/simulador",
    "benchmark": "/app/benchmark",
}

#: As duas larguras do `010_DESIGN.md` §8. 1440 é a tela de trabalho; 390, a de bolso.
LARGURAS = ((1440, 900), (390, 844))

#: Mensagens de console que **não** contam como erro (as mesmas do `web_smoke.py`).
RUIDO_ACEITO = (
    "Download the React DevTools",
    "[vite] connected",
    "Failed to load resource:",
)


def _e_ruido(texto: str) -> bool:
    return any(marca in texto for marca in RUIDO_ACEITO)


def _encolher(caminho: pathlib.Path) -> None:
    """Reduz o PNG a 256 cores.

    Print de interface tem poucas cores — quatro superfícies, três tintas, meia dúzia de
    acentos —, e a paleta adaptativa é indistinguível a olho do original. O ganho não é
    estético: os 72 prints somam **18 MB** em 24 bits e **6,8 MB** em paleta, e eles vão
    para o repositório (D-197). A conta é a mesma do `web-smoke`, que não versiona os
    dele: blob grande em histórico não se apaga depois.
    """
    with Image.open(caminho) as imagem:
        paleta = imagem.convert("RGB").quantize(colors=256, method=Image.Quantize.MEDIANCUT)
        paleta.save(caminho, optimize=True)


def um_version_id(base: str) -> str:
    """Um id de versão real, da API: id escrito no código funciona hoje e dá 404 amanhã."""
    with httpx.Client(base_url=base, timeout=20.0) as cliente:
        veiculos = cliente.get("/api/v1/vehicles", headers={"X-Role": "gestor"})
        veiculos.raise_for_status()
    lista = veiculos.json()
    if not lista:
        raise SystemExit("a base nao tem veiculo: rode scripts/demo/preparar_base.py")
    # A que tem ficha, e não a primeira: a ficha da versão vazia não mostra nada do desenho.
    for veiculo in lista:
        if "Limited" in veiculo["versao"]:
            return veiculo["id"]
    return lista[0]["id"]


def _entrar(pagina, base: str, papel: str) -> None:
    """Abre o app e troca para o papel pelo seletor da barra lateral (D-204: sem login).

    A 390 px a barra lateral não existe: a navegação é a barra inferior e os papéis ficam
    dentro de "mais". Esperar pelo seletor da sidebar ali é esperar por algo que o CSS
    escondeu — foi o que travou o primeiro print de 390 px desta rodada.
    """
    pagina.goto(f"{base}/app/consulta", wait_until="domcontentloaded")
    atual = pagina.get_by_test_id("papel-atual")
    atual.wait_for(state="attached", timeout=15_000)
    if atual.inner_text().strip().lower() == papel:
        return
    if pagina.get_by_test_id("trocar-papel").is_visible():
        pagina.get_by_test_id("trocar-papel").click()
        opcao = pagina.get_by_test_id(f"papel-{papel}")
    else:
        pagina.get_by_role("button", name="mais").click()
        opcao = pagina.get_by_test_id(f"papel-celular-{papel}")
    opcao.wait_for(state="visible", timeout=15_000)
    opcao.click()
    pagina.wait_for_function(
        "papel => document.querySelector('[data-testid=papel-atual]')"
        "?.textContent?.trim()?.toLowerCase() === papel",
        arg=papel,
        timeout=15_000,
    )


def main() -> int:
    analise = argparse.ArgumentParser(description=__doc__)
    analise.add_argument("--base", default="http://127.0.0.1:8012")
    analise.add_argument("--papeis", default="analista")
    analise.add_argument("--telas", default=",".join(ROTAS))
    analise.add_argument("--saida", default=str(SAIDA_PADRAO.relative_to(RAIZ).as_posix()))
    argumentos = analise.parse_args()

    saida = RAIZ / argumentos.saida
    base = argumentos.base.rstrip("/")
    papeis = tuple(p.strip() for p in argumentos.papeis.split(",") if p.strip())
    telas = tuple(t.strip() for t in argumentos.telas.split(",") if t.strip() in ROTAS)

    version_id = um_version_id(base)
    saida.mkdir(parents=True, exist_ok=True)
    relatorio: list[dict] = []

    with sync_playwright() as p:
        navegador = p.chromium.launch()
        for papel in papeis:
            for largura, altura in LARGURAS:
                contexto = navegador.new_context(viewport={"width": largura, "height": altura})
                pagina = contexto.new_page()
                erros: list[str] = []

                # Funções nomeadas, e não `lambda`: um `lambda` dentro do laço fecha sobre
                # a **variável** `erros`, não sobre o valor dela, e na volta seguinte
                # passaria a escrever na lista do contexto novo (ruff B023).
                def ao_console(msg, destino: list[str] = erros) -> None:
                    if msg.type == "error" and not _e_ruido(msg.text):
                        destino.append(msg.text)

                def ao_erro(exc, destino: list[str] = erros) -> None:
                    destino.append(f"exceção: {exc}")

                pagina.on("console", ao_console)
                pagina.on("pageerror", ao_erro)

                for tela in telas:
                    antes = len(erros)
                    destino = saida / papel / f"{tela}-{largura}.png"
                    destino.parent.mkdir(parents=True, exist_ok=True)
                    try:
                        if "/app/" not in pagina.url:
                            _entrar(pagina, base, papel)
                        rota = ROTAS[tela].format(version_id=version_id)
                        pagina.goto(f"{base}{rota}", wait_until="networkidle", timeout=30_000)
                        pagina.wait_for_timeout(400)
                        pagina.screenshot(path=str(destino), full_page=True)
                        _encolher(destino)
                    except ErroDoPlaywright as exc:
                        erros.append(f"{tela}: {str(exc).splitlines()[0]}")
                    relatorio.append(
                        {
                            "papel": papel,
                            "tela": tela,
                            "largura": largura,
                            "arquivo": str(destino.relative_to(RAIZ).as_posix()),
                            "erros": erros[antes:],
                        }
                    )
                    marca = "ok " if not erros[antes:] else "ERRO"
                    print(f"   {marca} {papel:9s} {tela:10s} {largura}px")
                contexto.close()
        navegador.close()

    (saida / "prints.json").write_text(
        json.dumps(relatorio, indent=2, ensure_ascii=False), encoding="utf-8", newline="\n"
    )
    comErro = [r for r in relatorio if r["erros"]]
    print(f"\n{len(relatorio)} prints em {saida.relative_to(RAIZ).as_posix()}")
    if comErro:
        print(f"ATENCAO: {len(comErro)} com erro de console:")
        for item in comErro:
            print(f"   {item['papel']}/{item['tela']}-{item['largura']}: {item['erros']}")
    return 1 if comErro else 0


if __name__ == "__main__":
    raise SystemExit(main())
