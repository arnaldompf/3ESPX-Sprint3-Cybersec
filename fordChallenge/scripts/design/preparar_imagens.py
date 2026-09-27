#!/usr/bin/env python
"""As fotos dos veículos e o logo da Ford, do que o time entregou para o que a tela usa.

    python scripts/design/preparar_imagens.py

Entrada: `imagens/`, como o time entregou (PNG grandes e um zip com o logo).
Saída:   `web/public/img/veiculos/*.webp`, `web/public/img/marca/ford.svg` e
         `web/public/img/CREDITOS.md`.

**Por que um script, e não cinco conversões à mão.** O recorte 16:9 não é centralizado na
imagem: ele é centralizado no **veículo**. As fotos vêm com margens desiguais — a Hilux
tem 1708×921 e a S10 1773×887, e um corte central cego decepa a caçamba de uma e o capô da
outra. O script acha a caixa do que não é fundo e centra a janela nela, o que dá o mesmo
enquadramento nas cinco. Repetir isso à mão cinco vezes é errar uma.

**Formato.** WebP com qualidade 82 e no máximo 1600 px de largura. As cinco somam menos de
500 KB contra 8,6 MB dos PNG de origem, e elas aparecem em dois lugares onde o tamanho
importa: o topo da Ficha e as duas colunas do Showroom, que carregam no tablet do salão.

**O logo.** O zip chama-se "logoFordVetorizada" e traz um EPS gerado pelo cairo. Esta
máquina não tem Inkscape, Ghostscript nem ImageMagick, e o EPS não é um raster embrulhado:
são caminhos de Bézier de verdade, num subconjunto pequeno e previsível do PostScript. O
conversor abaixo lê esse subconjunto e escreve SVG — 7 KB, nítido em qualquer tamanho,
fundo transparente. Conferido contra o JPG do mesmo zip, lado a lado, num Chromium.
"""

from __future__ import annotations

import pathlib
import re
import sys
import zipfile

RAIZ = pathlib.Path(__file__).resolve().parents[2]
ORIGEM = RAIZ / "imagens"
DESTINO_VEICULOS = RAIZ / "web" / "public" / "img" / "veiculos"
DESTINO_MARCA = RAIZ / "web" / "public" / "img" / "marca"
CREDITOS = RAIZ / "web" / "public" / "img" / "CREDITOS.md"

#: Arquivo de origem → nome na tela. O nome é o que a URL mostra; o de origem é o que o
#: time mandou, com espaço e tudo.
FOTOS: dict[str, str] = {
    "range raptor.png": "ranger-raptor",
    "ranger limited.png": "ranger-limited",
    "Hilux SRX Plus.png": "hilux-srx-plus",
    "Amarok V6 Extreme.png": "amarok-v6-extreme",
    "S10 High Country.png": "s10-high-country",
}

LARGURA_MAXIMA = 1600
PROPORCAO = 16 / 9
QUALIDADE = 82


#: Luminância acima da qual um pixel é candidato a fundo, e quanta cor ele pode ter.
#: Medidos na `S10 High Country.png`: o xadrez alterna (254,254,254) e (238,238,238), com
#: ruído de compressão de ±2. A picape mais clara da foto é o para-choque prateado, bem
#: abaixo disso, e o que for claro **dentro** dela não é alcançado pelo alastramento.
LIMIAR_DE_CLARO = 228
LIMIAR_DE_COR = 12

#: A média dos dois cinzas do quadriculado medido: (254,254,254) e (238,238,238).
CINZA_DO_VIDRO = 246


def sem_xadrez(imagem):
    """Torna transparente o fundo **quadriculado** que veio pintado na imagem.

    Defeito medido em 12/09/2026: a `S10 High Country.png` chegou em RGB, sem canal alfa, e
    com o xadrez cinza-e-branco de "isto é transparente" **desenhado nos pixels**. Na tela
    ele aparece como xadrez mesmo — foi o que o contato de prova mostrou, ao lado de quatro
    fotos recortadas de verdade.

    O que faz e o que não faz: marca como fundo os pixels claros e sem cor **ligados à
    borda**, por alastramento. Ligação à borda é o que protege a picape: o para-choque
    prateado e o vidro claro não tocam a moldura, então não são alcançados por mais claros
    que sejam. Um recorte por cor sozinho comeria os dois.
    """
    import numpy as np
    from PIL import Image

    rgb = np.asarray(imagem.convert("RGB"), dtype=np.int16)
    claro = rgb.max(axis=2) >= LIMIAR_DE_CLARO
    sem_cor = (rgb.max(axis=2) - rgb.min(axis=2)) <= LIMIAR_DE_COR
    candidato = claro & sem_cor

    # Alastramento a partir da moldura, em ondas: a máscara cresce enquanto encostar em
    # candidato novo. `np.roll` nas quatro direções é o vizinho de 4 conexões.
    fundo = np.zeros_like(candidato)
    fundo[0, :] = candidato[0, :]
    fundo[-1, :] = candidato[-1, :]
    fundo[:, 0] = candidato[:, 0]
    fundo[:, -1] = candidato[:, -1]
    while True:
        vizinhos = fundo.copy()
        vizinhos[1:, :] |= fundo[:-1, :]
        vizinhos[:-1, :] |= fundo[1:, :]
        vizinhos[:, 1:] |= fundo[:, :-1]
        vizinhos[:, :-1] |= fundo[:, 1:]
        crescido = vizinhos & candidato
        if crescido.sum() == fundo.sum():
            break
        fundo = crescido

    # O xadrez **dentro** do para-brisa: ele aparece através do vidro semitransparente e
    # não toca a borda, então o alastramento — corretamente — não o alcança. Apagá-lo
    # deixaria um buraco no vidro; o que se faz é achatar os dois cinzas do quadriculado
    # na média deles, o que apaga a grade e muda cada pixel em no máximo 8 de 255. A
    # 330 px na coluna do Showroom a diferença entre os dois já é o que se enxerga.
    preso = candidato & ~fundo
    liso = rgb.copy()
    liso[preso] = CINZA_DO_VIDRO

    alfa = np.where(fundo, 0, 255).astype(np.uint8)
    saida = Image.fromarray(liso.astype(np.uint8), mode="RGB").convert("RGBA")
    saida.putalpha(Image.fromarray(alfa, mode="L"))
    return saida


def caixa_do_veiculo(imagem):
    """A caixa do que **não** é fundo: por alfa quando há, por contraste quando não há.

    As quatro primeiras fotos vieram recortadas, com alfa de verdade; a S10 veio com o
    xadrez pintado e passa por `sem_xadrez` antes de chegar aqui.
    """
    from PIL import Image, ImageChops

    if imagem.mode == "RGBA":
        caixa = imagem.getchannel("A").getbbox()
        if caixa:
            return caixa
    cinza = imagem.convert("L")
    # `difference` contra o branco: o que sobra é a tinta. `getbbox` ignora o zero.
    tinta = ImageChops.difference(cinza, Image.new("L", cinza.size, 255))
    return tinta.getbbox() or (0, 0, *imagem.size)


def recortar_16_9(imagem):
    """Janela 16:9 centrada no veículo, sem sair da imagem."""
    largura, altura = imagem.size
    esquerda, topo, direita, base = caixa_do_veiculo(imagem)
    centro_x = (esquerda + direita) / 2
    centro_y = (topo + base) / 2

    if largura / altura > PROPORCAO:
        # Larga demais: corta dos lados.
        nova_largura, nova_altura = round(altura * PROPORCAO), altura
    else:
        nova_largura, nova_altura = largura, round(largura / PROPORCAO)

    x0 = min(max(round(centro_x - nova_largura / 2), 0), largura - nova_largura)
    y0 = min(max(round(centro_y - nova_altura / 2), 0), altura - nova_altura)
    return imagem.crop((x0, y0, x0 + nova_largura, y0 + nova_altura))


def converter_fotos() -> list[str]:
    from PIL import Image

    DESTINO_VEICULOS.mkdir(parents=True, exist_ok=True)
    linhas: list[str] = []
    for arquivo, nome in FOTOS.items():
        entrada = ORIGEM / arquivo
        if not entrada.exists():
            linhas.append(f"{nome}: FALTA {arquivo}")
            continue
        with Image.open(entrada) as bruta:
            bruta.load()
            # Sem canal alfa, o fundo pode ser xadrez pintado (o caso da S10).
            imagem = bruta if bruta.mode == "RGBA" else sem_xadrez(bruta)
            recorte = recortar_16_9(imagem)
            if recorte.width > LARGURA_MAXIMA:
                nova_altura = round(recorte.height * LARGURA_MAXIMA / recorte.width)
                recorte = recorte.resize((LARGURA_MAXIMA, nova_altura), Image.LANCZOS)
            saida = DESTINO_VEICULOS / f"{nome}.webp"
            recorte.save(saida, "WEBP", quality=QUALIDADE, method=6)
        kb = saida.stat().st_size / 1024
        linhas.append(f"{nome}: {recorte.width}x{recorte.height} · {kb:.0f} KB")
    return linhas


# ----------------------------------------------------------------- o logo, EPS -> SVG
def _numero(texto: str) -> str:
    """Coordenada com duas casas. Corta perto de 40% do tamanho do SVG e não se vê."""
    valor = round(float(texto), 2)
    return str(int(valor)) if valor == int(valor) else f"{valor:g}"


#: Um número do PostScript. Tudo que não casa aqui é operador, e todo operador que este
#: conversor não conhece (recorte da página inteira, transformações de identidade, o flip
#: inicial que já deixa as coordenadas no sentido do SVG) simplesmente **esvazia a pilha**:
#: o que estava nela eram os argumentos dele.
NUMERO = re.compile(r"-?[0-9]+([.][0-9]+)?(e-?[0-9]+)?")


def _hexadecimal(vermelho: float, verde: float, azul: float) -> str:
    """Cor do PostScript (0 a 1 por canal) em `#rrggbb`."""
    return "#" + "".join(f"{round(canal * 255):02x}" for canal in (vermelho, verde, azul))


def eps_para_svg(eps: str) -> str:
    """O subconjunto do PostScript que o cairo emite, em SVG.

    `m` `l` `c` `h` viram `M` `L` `C` `Z`; `rg` e `g` viram a cor do preenchimento; `f` e
    `f*` fecham o caminho (o segundo com `fill-rule="evenodd"`).
    """
    caixa = re.search(r"%%BoundingBox:\s*(\d+)\s+(\d+)\s+(\d+)\s+(\d+)", eps)
    if not caixa:
        raise SystemExit("EPS sem %%BoundingBox: nao e o formato esperado")
    largura, altura = int(caixa.group(3)), int(caixa.group(4))

    palavras = eps[eps.index("%%EndSetup") :].replace("\n", " ").split()
    pilha: list[str] = []
    caminho: list[str] = []
    cor = "#000000"
    partes: list[str] = []

    for palavra in palavras:
        if NUMERO.fullmatch(palavra):
            pilha.append(palavra)
            continue
        if palavra == "m" and len(pilha) >= 2:
            caminho.append("M" + " ".join(_numero(v) for v in pilha[-2:]))
        elif palavra == "l" and len(pilha) >= 2:
            caminho.append("L" + " ".join(_numero(v) for v in pilha[-2:]))
        elif palavra == "c" and len(pilha) >= 6:
            caminho.append("C" + " ".join(_numero(v) for v in pilha[-6:]))
        elif palavra == "h":
            caminho.append("Z")
        elif palavra == "rg" and len(pilha) >= 3:
            cor = _hexadecimal(*(float(v) for v in pilha[-3:]))
        elif palavra == "g" and len(pilha) >= 1:
            claro = float(pilha[-1])
            cor = _hexadecimal(claro, claro, claro)
        elif palavra in {"f", "f*"}:
            if caminho:
                regra = ' fill-rule="evenodd"' if palavra.endswith("*") else ""
                partes.append(f'<path fill="{cor}"{regra} d="{"".join(caminho)}"/>')
            caminho.clear()
        pilha.clear()

    if not partes:
        raise SystemExit("nenhum caminho convertido: o EPS nao e o formato esperado")
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {largura} {altura}" '
        f'role="img" aria-label="Ford">\n  ' + "\n  ".join(partes) + "\n</svg>\n"
    )


def converter_logo() -> str:
    zip_do_logo = ORIGEM / "logoFordVetorizada.zip"
    if not zip_do_logo.exists():
        return "ford.svg: FALTA logoFordVetorizada.zip"
    with zipfile.ZipFile(zip_do_logo) as pacote:
        nomes = [n for n in pacote.namelist() if n.lower().endswith(".eps")]
        if not nomes:
            return "ford.svg: o zip nao tem .eps"
        bruto = pacote.read(nomes[0]).decode("latin-1")
    svg = eps_para_svg(bruto)
    DESTINO_MARCA.mkdir(parents=True, exist_ok=True)
    saida = DESTINO_MARCA / "ford.svg"
    saida.write_text(svg, encoding="utf-8", newline="\n")
    return f"ford.svg: {len(svg) / 1024:.1f} KB, {svg.count('<path')} caminho(s)"


TEXTO_DOS_CREDITOS = """# Créditos das imagens

As fotos dos cinco veículos são **divulgação oficial das montadoras, fornecidas pelo
time**. Elas aparecem em dois lugares e em tamanho pequeno: no topo da Ficha técnica e nas
duas colunas do Showroom. Nenhuma é usada como fundo de tela, e nenhuma carrega informação
que o produto afirme — o que o SpecRadar afirma tem evidência, e foto não é evidência.

| Arquivo | Veículo |
|---|---|
| `veiculos/ranger-raptor.webp` | Ford Ranger Raptor 3.0 V6 Bi-turbo 4WD AT |
| `veiculos/ranger-limited.webp` | Ford Ranger Limited 3.0 V6 Diesel 4WD AT |
| `veiculos/hilux-srx-plus.webp` | Toyota Hilux SRX Plus AT |
| `veiculos/amarok-v6-extreme.webp` | Volkswagen Amarok V6 Extreme |
| `veiculos/s10-high-country.webp` | Chevrolet S10 High Country |

`marca/ford.svg` é o logo da Ford, convertido do EPS de `imagens/logoFordVetorizada.zip`
(o arquivo que o time entregou). Ele aparece **uma vez**, no rodapé da barra lateral, ao
lado de "Ford Challenge FIAP 2026".

## O arquivo da S10 chegou diferente dos outros quatro

As quatro primeiras fotos vieram recortadas, com transparência de verdade. A
`S10 High Country.png` veio em RGB, **com o quadriculado de "isto é transparente"
desenhado nos pixels**. O preparo apaga o quadriculado do fundo (por alastramento a partir
da borda, o que protege o para-choque prateado) e achata os dois cinzas do que ficou preso
dentro do vidro.

**O que sobra, e está dito porque sobra:** no para-brisa, onde o quadriculado aparece
através do vidro escurecido, ele cai abaixo do limiar de claro e não é tratado. Aos 220 e
330 px em que a foto aparece na tela, o resto se confunde com reflexo. Tratá-lo exigiria
baixar o limiar a ponto de apagar reflexo de verdade, e repintar foto de montadora não é
coisa que este projeto faça. Quem tiver o arquivo original sem o quadriculado, troque em
`imagens/` e rode o preparo de novo.

## Duas ressalvas, e as duas são de quem apresenta

1. **`design-kit/020_BRIEF_PRODUTO.md` §identidade diz "não usar nem redesenhar logos da
   Ford ou da FIAP dentro do produto".** O logo está aqui porque a instrução da noite de
   12/09/2026 pediu, explicitamente, o logo no rodapé da barra lateral. A instrução é
   posterior e do dono do produto; o registro fica em `DECISOES_NOITE.md` D-213.
2. **O arquivo do zip vem do Vecteezy**, não do banco de marca da Ford: o pacote inclui
   `Vecteezy-License-Information.pdf`. Para uma apresentação interna isso não é problema.
   Para qualquer material que circule fora, a arte oficial tem de vir da Ford.

Gerado por `scripts/design/preparar_imagens.py`. Os originais ficam em `imagens/`.
"""


def main() -> int:
    try:
        import PIL  # noqa: F401
    except ImportError:
        print("FALTA: Pillow. Rode `uv sync`.")
        return 2

    print("-- fotos dos veiculos")
    for linha in converter_fotos():
        print(f"   {linha}")
    print("-- logo")
    print(f"   {converter_logo()}")
    CREDITOS.parent.mkdir(parents=True, exist_ok=True)
    CREDITOS.write_text(TEXTO_DOS_CREDITOS, encoding="utf-8", newline="\n")
    print(f"-- creditos: {CREDITOS.relative_to(RAIZ)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
