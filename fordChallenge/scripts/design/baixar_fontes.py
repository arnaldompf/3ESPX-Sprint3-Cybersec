"""Baixa as fontes do web app para `web/public/fonts` e gera o `fontes.css`.

**Por que fontes locais e não `<link>` para o Google.** Três razões, em ordem de peso:

1. a apresentação de 15/09 acontece numa sala, e uma sala pode não ter internet. Fonte que
   depende de CDN vira fallback de sistema no pior momento possível;
2. a CSP do web app é `default-src 'none'` com `font-src 'self'` (`api/app/middleware.py`).
   Servir do próprio app não exige abrir exceção para domínio de terceiro — e cada exceção
   numa CSP é uma porta que alguém precisa justificar depois;
3. nenhum IP de quem usa o sistema chega a um servidor de terceiro só para desenhar texto.

**O que é baixado.** Os arquivos de **eixo variável** (`wght`), um por subset. `latin` cobre
o português do Brasil inteiro (`ã`, `ç`, `õ` estão em U+0000-00FF) e `latin-ext` entra
porque custa ~20 KB e cobre nome próprio estrangeiro. Sem itálico: a interface não usa.

**Licença.** As quatro famílias são SIL Open Font License 1.1, que permite uso e
redistribuição embutida. `web/public/fonts/LICENSES.md` guarda a atribuição.

Rodar (precisa de rede, e é a única coisa neste repositório que precisa):

    python scripts/design/baixar_fontes.py
"""

from __future__ import annotations

import json
import pathlib
import re
import urllib.request

RAIZ = pathlib.Path(__file__).resolve().parents[2]
DESTINO = RAIZ / "web" / "public" / "fonts"

#: O Google Fonts devolve `woff2` de eixo variável só para navegador moderno; com o
#: user-agent do `urllib` ele responde `ttf`, que é 4x maior e sem o eixo.
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

#: apelido do arquivo -> (nome da família, faixa de pesos pedida ao Google, faixa no @font-face)
FAMILIAS: dict[str, tuple[str, str, str]] = {
    "SchibstedGrotesk": ("Schibsted Grotesk", "Schibsted+Grotesk:wght@400..700", "400 700"),
    "HankenGrotesk": ("Hanken Grotesk", "Hanken+Grotesk:wght@400..700", "400 700"),
    "PublicSans": ("Public Sans", "Public+Sans:wght@400..700", "400 700"),
    "JetBrainsMono": ("JetBrains Mono", "JetBrains+Mono:wght@400..600", "400 600"),
}

SUBSETS = ("latin", "latin-ext")


#: O bloco `@font-face` de um subset, como o Google Fonts o escreve.
UM_FONT_FACE = re.compile(r"/\*\s*([a-z-]+)\s*\*/\s*@font-face\s*\{(.*?)\}", re.S)


def _baixar(url: str) -> bytes:
    pedido = urllib.request.Request(url, headers={"User-Agent": UA})  # noqa: S310  (host fixo)
    with urllib.request.urlopen(pedido, timeout=60) as resposta:  # noqa: S310
        return resposta.read()


def main() -> int:
    DESTINO.mkdir(parents=True, exist_ok=True)
    blocos_css: list[str] = []
    relatorio: dict[str, list[dict]] = {}

    for apelido, (nome, spec, pesos) in FAMILIAS.items():
        css = _baixar(f"https://fonts.googleapis.com/css2?family={spec}&display=swap").decode()
        achados: list[dict] = []
        for subset, corpo in UM_FONT_FACE.findall(css):
            if subset not in SUBSETS:
                continue
            url = re.search(r"url\((https://[^)]+\.woff2)\)", corpo)
            faixa = re.search(r"unicode-range:\s*([^;]+);", corpo)
            if not url or not faixa:
                continue
            arquivo = f"{apelido}-{subset}.woff2"
            (DESTINO / arquivo).write_bytes(_baixar(url.group(1)))
            achados.append(
                {
                    "subset": subset,
                    "arquivo": arquivo,
                    "range": faixa.group(1).strip(),
                    "bytes": (DESTINO / arquivo).stat().st_size,
                    "origem": url.group(1),
                }
            )
            blocos_css.append(
                "\n".join(
                    [
                        f"/* {nome} — {subset} */",
                        "@font-face {",
                        f"  font-family: '{nome}';",
                        "  font-style: normal;",
                        f"  font-weight: {pesos};",
                        # `swap`: texto legível desde o primeiro quadro. Com `block` a tela
                        # fica em branco até a fonte chegar, e branco é o defeito que esta
                        # rodada inteira existe para não repetir.
                        "  font-display: swap;",
                        f"  src: url('/app/fonts/{arquivo}') format('woff2');",
                        f"  unicode-range: {faixa.group(1).strip()};",
                        "}",
                        "",
                    ]
                )
            )
        relatorio[apelido] = achados
        print(f"{nome}: " + ", ".join(f"{a['arquivo']} ({a['bytes'] // 1024} KB)" for a in achados))

    cabecalho = [
        "/* Fontes locais do SpecRadar. GERADO por scripts/design/baixar_fontes.py.",
        " *",
        " * Nenhuma requisicao sai para fonts.googleapis.com em tempo de execucao: a CSP do",
        " * app e `default-src 'none'` com `font-src 'self'`, e a apresentacao acontece numa",
        " * sala que pode nao ter internet.",
        " *",
        " * SIL Open Font License 1.1 — atribuicao em LICENSES.md, nesta pasta.",
        " */",
        "",
    ]
    (DESTINO / "fontes.css").write_text(
        "\n".join(cabecalho) + "\n".join(blocos_css), encoding="utf-8", newline="\n"
    )
    (DESTINO / "fontes.json").write_text(
        json.dumps(relatorio, indent=2, ensure_ascii=False), encoding="utf-8", newline="\n"
    )
    print(f"\nfontes.css e fontes.json em {DESTINO.relative_to(RAIZ).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
