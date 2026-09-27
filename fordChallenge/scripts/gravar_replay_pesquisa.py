"""Grava o **modo replay** do Pesquisador a partir de uma pesquisa feita ao vivo.

**O plano B da apresentação de 15/09.** A cena 13 mostra o sistema procurando um veículo
que ninguém coletou. Se a internet do auditório cair — e ela cai —, a cena tem de rodar
igual: mesmas consultas, mesmas páginas, mesmos números, sem uma requisição saindo.

O que este script faz:

1. roda a pesquisa **ao vivo** (ou reaproveita o cache de busca do dia);
2. copia as respostas de busca para `tests/fixtures/search/`, com a chave que o provedor
   `replay` procura;
3. garante que as **páginas** também estão salvas — a coleta já grava snapshot com hash,
   então isso é conferência, não cópia.

A etiqueta da data entra no arquivo: quem assistir à demonstração tem de poder saber que
está vendo uma gravação de 13/09/2026, e não uma busca de agora. **Fingir que é ao vivo
seria mentir sobre a única coisa que o produto vende.**

    python scripts/gravar_replay_pesquisa.py "RAM|Rampage|Laramie 2.0 Turbodiesel AT9 4x4"
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

DESTINO = RAIZ / "tests" / "fixtures" / "search"


def gravar(marca: str, modelo: str, versao: str, *, ao_vivo: bool) -> int:
    from pipeline.research import planner
    from pipeline.research import search as busca

    alvo = planner.Alvo(marca, modelo, versao)
    consultas = planner.primeira_rodada(alvo)
    provedor = busca.provedor_configurado() or "tavily"
    hoje = datetime.now(UTC).strftime("%Y-%m-%d")
    DESTINO.mkdir(parents=True, exist_ok=True)

    gravadas = 0
    vazias = 0
    for consulta in consultas:
        if ao_vivo:
            resposta = busca.buscar(consulta.texto, provedor=provedor)
            achados = [a.to_dict() for a in resposta.achados]
            if not resposta.ok:
                print(f"  !  {consulta.texto[:60]}: {resposta.erro[:80]}")
                continue
        else:
            origem = busca.CACHE / hoje / f"{busca._chave(consulta.texto, provedor, hoje)}.json"
            if not origem.exists():
                print(f"  -  sem cache: {consulta.texto[:60]}")
                vazias += 1
                continue
            achados = json.loads(origem.read_text(encoding="utf-8")).get("achados", [])

        alvo_arquivo = DESTINO / f"{busca._chave(consulta.texto, 'replay', 'fixture')}.json"
        alvo_arquivo.write_text(
            json.dumps(
                {
                    "consulta": consulta.texto,
                    "provedor": "replay",
                    "veiculo": alvo.nome,
                    "gravado_em": hoje,
                    "gravado_de": provedor,
                    "achados": achados,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        gravadas += 1
        print(f"  ok {len(achados):2d} resultado(s)  {consulta.texto[:62]}")

    print(f"\n{gravadas} consulta(s) gravada(s) em {DESTINO.relative_to(RAIZ)}")
    if vazias:
        print(f"{vazias} sem cache — rode com --ao-vivo para buscá-las")
    return gravadas


#: Onde as páginas promovidas ficam.
#:
#: `tests/fixtures/snapshots/` e **não** `data/snapshots/`: `data/` está no `.gitignore`, e
#: uma gravação que só existe nesta máquina não é plano B para a apresentação — é plano B
#: para esta máquina. O plano B tem de sobreviver a um clone.
SNAPSHOTS = RAIZ / "tests" / "fixtures" / "snapshots"

#: Teto de texto de uma página promovida.
#:
#: O mesmo do Pesquisador, e pelo mesmo motivo: uma ficha técnica tem dezenas de KB. As 18
#: páginas da primeira rodada ao vivo somaram 141,7 MB de manuais do proprietário — isso não
#: pode entrar no repositório, e não serviria de nada se entrasse.
TETO_DE_TEXTO = 2_000_000


def promover_paginas(dia: str, modelos: list[str]) -> int:
    """Promove as páginas do cache de coleta a **snapshots de replay**.

    Sem isto, gravar só as respostas de busca não basta: em replay o `fetch` resolve URL →
    snapshot salvo, e o cache de HTTP (`data/cache/<dia>/`) **não** é consultado por ele.
    A cena rodaria com as consultas certas e zero páginas — que é o pior dos dois mundos,
    porque parece funcionar até a ficha sair vazia.

    O `source_id` sai do domínio, e o `tier` é reavaliado pelo classificador: uma página
    promovida tem de entrar no replay com a mesma autoridade que teria ao vivo.
    """
    import hashlib
    import re

    from pipeline.research import classify

    # **O mesmo portão de `tests/eval/test_fixtures.py`.** Página de terceiro em HTML bruto
    # traz o JavaScript do site junto, e o JavaScript traz a chave de API **deles**: a
    # primeira gravação parou no teste de segredo por causa de um `apiKey=` numa página do
    # Webmotors. Não é segredo nosso, e não muda nada: uma fixture com chave de terceiro
    # dentro não entra num repositório que vai para o GitHub.
    suspeitos = re.compile(
        r"(sk-[A-Za-z0-9]{20,}|api[_-]?key\s*[:=]\s*['\"][^'\"]{16,}"
        r"|BEGIN [A-Z ]*PRIVATE KEY)",
        re.IGNORECASE,
    )

    origem = RAIZ / "data" / "cache" / dia
    if not origem.exists():
        print(f"sem cache de coleta em {origem.relative_to(RAIZ)}")
        return 0

    promovidas = 0
    for arquivo in sorted(origem.glob("*.json")):
        try:
            dados = json.loads(arquivo.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        url = dados.get("url") or ""
        texto = dados.get("texto") or ""
        if not url or not texto:
            continue

        dominio = classify.dominio_de(url)
        # O cache não sabe de qual veículo a página veio, então a marca é inferida: se
        # alguma das marcas conhecidas reconhece o domínio como oficial, é dela. Sem isso,
        # `vw.com.br` seria "domínio não reconhecido" e a página da montadora seria pulada.
        decisao = classify.classificar(url)
        for marca_conhecida in classify.OFICIAIS:
            tentativa = classify.classificar(url, marca=marca_conhecida)
            if tentativa.tier < decisao.tier:
                decisao = tentativa

        # **O mesmo filtro do Pesquisador**, aplicado à gravação — e o de relevância também.
        # O cache do dia guarda tudo o que foi coletado, inclusive de outras pesquisas; sem
        # a pergunta "esta página fala de algum dos modelos pedidos?", a gravação levava
        # para o repositório o manual da Amarok e o regulamento de um festival de cultura
        # japonesa hospedado no domínio da Nissan. Os dois são T1. Nenhum é ficha técnica.
        if modelos and not any(classify.fala_do_modelo(url, "", m) for m in modelos):
            continue
        if not decisao.aceita:
            print(f"  -  pulada ({decisao.motivo[:40]}): {url[:52]}")
            continue
        if len(texto) > TETO_DE_TEXTO:
            print(f"  -  pulada ({len(texto) / 1_000_000:.1f} M de caracteres): {url[:44]}")
            continue
        if suspeitos.search(texto):
            print(f"  -  pulada (parece carregar chave de terceiro): {url[:44]}")
            continue
        version_id = "pesquisa_" + dominio.replace(".", "_").replace("-", "_")
        source_id = (
            dominio.replace(".", "_").replace("-", "_")
            + "_"
            + hashlib.sha256(url.encode("utf-8")).hexdigest()[:8]
        )

        pasta = SNAPSHOTS / version_id / f"{dia}T00-00-00Z" / source_id
        pasta.mkdir(parents=True, exist_ok=True)
        (pasta / "doc.md").write_text(texto, encoding="utf-8")
        (pasta / "meta.json").write_text(
            json.dumps(
                {
                    "source_id": source_id,
                    "version_id": version_id,
                    "url_final": dados.get("url_final") or url,
                    "url": url,
                    "http_status": dados.get("http_status", 200),
                    "tier": decisao.tier,
                    "tipo": "pdf_oficial" if decisao.e_pdf else "site_oficial",
                    "status": "consultada",
                    "captured_at": (dados.get("captured_at") or dia)[:10],
                    "text_path": "doc.md",
                    "sha256": dados.get("sha256", ""),
                    "bytes": len(texto.encode("utf-8")),
                    "gerado_por": "scripts/gravar_replay_pesquisa.py",
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        promovidas += 1

    print(f"{promovidas} página(s) promovida(s) a snapshot de replay")
    return promovidas


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("veiculo", nargs="+", help='"Marca|Modelo|Versão"')
    parser.add_argument(
        "--ao-vivo", action="store_true", help="busca de verdade (consome cota do provedor)"
    )
    parser.add_argument(
        "--promover-paginas",
        metavar="DIA",
        help="promove `data/cache/<DIA>/` a snapshots de replay (ex.: 2026-09-13)",
    )
    args = parser.parse_args()

    import os

    if args.ao_vivo:
        os.environ["REPLAY_MODE"] = "0"

    total = 0
    for cru in args.veiculo:
        partes = cru.split("|", 2)
        marca, modelo = partes[0], partes[1] if len(partes) > 1 else ""
        versao = partes[2] if len(partes) > 2 else ""
        print(f"\ngravando: {marca} {modelo} {versao}".rstrip())
        total += gravar(marca, modelo, versao, ao_vivo=args.ao_vivo)

    if args.promover_paginas:
        print()
        modelos = [cru.split("|", 2)[1] for cru in args.veiculo if "|" in cru]
        promover_paginas(args.promover_paginas, modelos)

    print(f"\ntotal: {total} consulta(s). A cena 13 roda sem rede a partir de agora.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
