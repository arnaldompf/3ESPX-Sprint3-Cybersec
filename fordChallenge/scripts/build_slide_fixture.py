"""Gera o artefato da **referência interna da Ford** (o slide) como fonte do pipeline.

Por que este arquivo existe, e por que ele não é circularidade:

O "Fogo Amigo" — comparar o deck interno da Ford com o site oficial — é a cena-assinatura
do produto (`docs/13` §54). Para o pipeline **apontar** a divergência, o slide tem de ser
uma **fonte de entrada**, como qualquer outra. Hoje o conteúdo do slide está registrado em
`gabarito_v1.json` no campo `slide_ford`, porque foi lá que a coleta humana o anotou.

A distinção que importa: para os campos medidos, o gabarito-resposta é `esperado`, e nada
aqui o lê. O `slide_ford` é **dado do cliente** — a afirmação do deck, que o eval espera
ver *contestada*. Usá-lo como entrada é o oposto de circular: é submeter a afirmação do
slide ao mesmo grounding e às mesmas regras de status que qualquer fonte pública.

O slide entra como **tier 4**: documento interno, sem verificação editorial, abaixo de
oficial (T1), FIPE (T2) e imprensa (T3). É o que faz o valor público **vencer** e o do
slide ir para `conflicts` — a ficha mostra o valor certo e denuncia o deck, em vez de o
contrário.

Uso:  python scripts/build_slide_fixture.py [--check]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline.eval.gabarito import carregar_gabarito  # noqa: E402

DESTINO = ROOT / "tests" / "fixtures" / "slide"

#: Como o slide **rotula** cada bloco. Vem das notas do gabarito, não de invenção: a nota
#: de `modos_direcao` diz literalmente *"Slide diz 3 modos de 'volante'"*, e é esse rótulo
#: que faz o sinônimo volante≈direção ser exercitado de verdade.
ROTULOS = {
    "modos_conducao": "modos de condução",
    "modos_direcao": "modos de volante",
    "modos_escapamento": "modos de escapamento",
    "modos_amortecedor": "modos de amortecedor",
    "potencia_cv": "Potência",
    "potencia_rpm": "Potência máxima a",
    "torque_nm": "Torque",
    "torque_rpm": "Torque máximo a",
    "aceleracao_0_100_s": "0 a 100 km/h em",
    "tipo_tracao": "Tração",
    "amortecedores": "Amortecedores",
    "farois_tipo": "Faróis",
    "deslocamento_l": "Motor",
    "tipo": "Transmissão",
    "rodas_aro_pol": "Rodas e pneus",
    "preco_sugerido_brl": "Preço sugerido",
}
#: Unidade que o slide escreve junto do número, para o trecho ficar legível como deck.
UNIDADES = {
    "potencia_cv": "cv",
    "potencia_rpm": "rpm",
    "torque_nm": "Nm",
    "torque_rpm": "rpm",
    "aceleracao_0_100_s": "segundos",
}


def _linha(rotulo: str, valor) -> str:
    if isinstance(valor, list):
        nomes = ", ".join(v.replace("_", "-").capitalize() for v in valor)
        return f"{len(valor)} {rotulo} selecionáveis – {nomes}"
    return f"{rotulo}: {valor}"


def render(version_id: str) -> str:
    """Monta o texto do slide a partir do que a coleta anotou em `slide_ford`.

    Cada linha do deck aparece **uma vez**, com o rótulo que o slide usa. Nenhum valor é
    alterado: o que está em `slide_ford` é o que sai aqui, inclusive o typo de preço
    (`R$499.00`), que é parte fiel do documento.
    """
    veiculo = carregar_gabarito().por_id(version_id)
    linhas: list[str] = [
        f"# Referência interna Ford — {veiculo.marca} {veiculo.modelo} {veiculo.versao}",
        "",
        "Documento interno de treinamento comercial. NÃO é fonte pública.",
        "",
    ]
    vistos: set[str] = set()
    for campo in veiculo.campos_com_slide:
        chave = json.dumps(campo.slide_ford, ensure_ascii=False)
        if chave in vistos:
            continue
        vistos.add(chave)
        rotulo = ROTULOS.get(campo.campo, campo.campo.replace("_", " "))
        valor = campo.slide_ford
        if campo.campo in UNIDADES and not isinstance(valor, list):
            valor = f"{valor} {UNIDADES[campo.campo]}"
        linhas.append(f"* {_linha(rotulo, valor)}")
    return "\n".join(linhas) + "\n"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--check", action="store_true", help="confere sem escrever")
    p.add_argument("--veiculo", default="ford_ranger_raptor_2026")
    args = p.parse_args(argv if argv is not None else sys.argv[1:])

    texto = render(args.veiculo)
    caminho = DESTINO / f"{args.veiculo}.md"
    if args.check:
        atual = caminho.read_text(encoding="utf-8") if caminho.exists() else ""
        if atual != texto:
            print(f"DIVERGENTE: {caminho} nao bate com o que seria gerado")
            return 1
        print(f"ok: {caminho.relative_to(ROOT)} confere")
        return 0

    DESTINO.mkdir(parents=True, exist_ok=True)
    caminho.write_text(texto, encoding="utf-8", newline="\n")
    print(f"{caminho.relative_to(ROOT)}: {len(texto.splitlines())} linhas")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
