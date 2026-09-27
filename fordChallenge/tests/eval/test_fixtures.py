"""WP-02 — as fixtures de replay são o substrato de todo teste de pipeline.

Se elas apodrecerem, o eval mede o vazio e ninguém percebe. Estes testes travam:
o formato do snapshot, a coerência com `gabarito/raw/`, e o fato de que a evidência de
que o pipeline vai precisar **está** no texto salvo.
"""

from __future__ import annotations

import json
import re

import pytest

from pipeline.eval.compare import grounding
from pipeline.eval.gabarito import carregar_gabarito
from pipeline.store import FIXTURES, fontes_de, snapshots_de, textos_de


@pytest.fixture(scope="module")
def gab():
    return carregar_gabarito()


def test_todo_veiculo_do_gabarito_tem_snapshot(gab):
    for veiculo in gab.veiculos:
        assert snapshots_de(veiculo.id, FIXTURES), f"{veiculo.id} sem snapshot de replay"


def test_meta_json_tem_a_proveniencia_completa():
    for snap in snapshots_de("ford_ranger_raptor_2026", FIXTURES):
        for chave in ("url_final", "tier", "tipo", "captured_at", "sha256", "text_path"):
            assert chave in snap.meta, f"{snap.source_id} sem {chave}"
        assert 1 <= snap.tier <= 5
        assert snap.url.startswith("http")
        assert snap.texto, f"{snap.source_id} com texto vazio"


def test_snapshots_vem_ordenados_do_melhor_tier_para_o_pior():
    tiers = [s.tier for s in snapshots_de("vw_amarok_v6_extreme_2026", FIXTURES)]
    assert tiers == sorted(tiers)


def test_registro_de_evidencia_e_declarado_como_tal():
    """Registro de trecho não pode se passar por captura de página oficial."""
    snaps = {s.source_id: s for s in snapshots_de("ford_ranger_raptor_2026", FIXTURES)}
    registro = snaps["registro_evidencias_raptor"]
    assert registro.e_registro_de_evidencia
    assert registro.tipo == "registro_de_evidencia"
    assert "origem" in registro.meta
    pagina = snaps["ford_site_versao"]
    assert not pagina.e_registro_de_evidencia


def test_fonte_bloqueada_esta_registrada_com_status():
    """CAPTCHA da sala de imprensa da GM: fonte bloqueada vira status, nunca truque."""
    fontes = fontes_de("chevrolet_s10_high_country_2027", FIXTURES)
    bloqueadas = [f for f in fontes if f.status == "bloqueada"]
    assert len(bloqueadas) == 1
    assert "media.gm.com" in bloqueadas[0].url
    assert "CAPTCHA" in bloqueadas[0].nota


def test_fontes_json_lista_tambem_as_sem_texto_salvo():
    """`nao_encontrado` honesto exige a lista de fontes consultadas, com ou sem texto."""
    fontes = fontes_de("ford_ranger_raptor_2026", FIXTURES)
    assert any(not f.tem_texto_salvo for f in fontes), "faltam fontes sem texto salvo"
    assert any(f.tier == 2 for f in fontes), "FIPE tem de estar na lista de consultadas"
    assert any(f.tier == 3 for f in fontes), "imprensa tem de estar na lista de consultadas"


def test_fixtures_conferem_com_gabarito_raw():
    """As fixtures são geradas de `gabarito/raw/`; divergência silenciosa é proibida."""
    from scripts.build_fixtures import conferir

    assert conferir() == 0


def test_sha256_do_meta_bate_com_o_texto():
    import hashlib

    for snap in snapshots_de("toyota_hilux_srx_plus_at_2026", FIXTURES):
        esperado = hashlib.sha256(snap.texto.encode("utf-8")).hexdigest()
        assert snap.meta["sha256"] == esperado, snap.source_id


# ---------------------------------------------------------- a evidência está no texto
def _fragmentos(trecho: str) -> list[str]:
    """O `trecho` do gabarito é, em campo composto, uma montagem humana de várias frases.

    Ele traz `;` e `...` justamente onde o humano juntou itens separados da fonte. Para
    checar cobertura de evidência, o que importa é se cada **fragmento** existe no texto
    salvo — o `trecho` inteiro nunca foi um span verbatim único.
    """
    return [p.strip() for p in re.split(r"\s*(?:;|\.\.\.|…)\s*", trecho) if len(p.strip()) > 8]


@pytest.mark.parametrize(
    "version_id",
    [
        "ford_ranger_raptor_2026",
        "vw_amarok_v6_extreme_2026",
        "chevrolet_s10_high_country_2027",
    ],
)
def test_toda_evidencia_do_gabarito_esta_em_algum_texto_salvo(gab, version_id):
    """Precondição de `grounding_rate = 1,0`: sem texto, o pipeline não pode afirmar."""
    veiculo = gab.por_id(version_id)
    textos = list(textos_de(version_id, FIXTURES).values())
    assert textos
    faltando: list[str] = []
    for campo in veiculo.campos:
        if not campo.trecho:
            continue
        for fragmento in _fragmentos(campo.trecho):
            if not any(grounding(fragmento, t).ok for t in textos):
                faltando.append(f"{campo.origem}: {fragmento[:60]!r}")
    assert not faltando, "evidência sem texto salvo:\n" + "\n".join(sorted(set(faltando)))


def test_evidencia_da_hilux_esta_no_pdf_mas_em_leitura_de_tabela(gab):
    """A ficha da Hilux é tabela: o valor existe, só não como o `trecho` do gabarito.

    O gabarito registra `"204/ 3.400 (cv/rpm)"` — leitura por coluna, montada por humano.
    No texto salvo, a linha limpa é `Potência (cv/rpm)   204 / 3.400`. O que a WP-09 tem
    de entregar é essa linha; documentar isso aqui evita alguém "consertar" o gabarito.
    """
    textos = list(textos_de("toyota_hilux_srx_plus_at_2026", FIXTURES).values())
    assert any(grounding("204 / 3.400", t).ok for t in textos)
    assert any(grounding("50,9 / 2.800", t).ok for t in textos)
    assert any(grounding("265/60 R18", t).ok for t in textos)
    assert any(grounding("Liga leve 18", t).ok for t in textos)
    assert any(
        grounding("A-TRC (controle eletrônico de tração) com bloqueio", t).ok for t in textos
    )
    # ...e o `trecho` do gabarito, como span único, de fato não ocorre
    assert not any(grounding("204/ 3.400 (cv/rpm)", t).ok for t in textos)


def test_linha_vigente_da_hilux_esta_no_texto_salvo(gab):
    """O resolvedor (WP-07) precisa achar as 5 versões 2026 no snapshot de replay."""
    grs = gab.por_id("toyota_hilux_gr_sport_2026_inexistente")
    textos = list(textos_de(grs.id, FIXTURES).values())
    for nome in grs.nomes_da_linha_vigente:
        assert any(grounding(nome, t).ok for t in textos), nome


def test_nenhuma_fixture_carrega_segredo():
    """Nada de token, chave ou credencial nas fixtures versionadas."""
    suspeitos = re.compile(
        r"(sk-[A-Za-z0-9]{20,}|api[_-]?key\s*[:=]\s*['\"][^'\"]{16,}|BEGIN [A-Z ]*PRIVATE KEY)",
        re.IGNORECASE,
    )
    for arquivo in FIXTURES.rglob("*"):
        if arquivo.is_file() and arquivo.suffix in {".md", ".json"}:
            conteudo = arquivo.read_text(encoding="utf-8", errors="replace")
            assert not suspeitos.search(conteudo), f"possível segredo em {arquivo}"


def test_fixtures_nao_contem_dado_pessoal_de_cliente():
    """LGPD: nada de CPF nas fixtures."""
    cpf = re.compile(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b")
    for arquivo in FIXTURES.rglob("*"):
        if arquivo.is_file():
            texto = arquivo.read_text(encoding="utf-8", errors="replace")
            assert not cpf.search(texto), f"CPF em {arquivo}"


def test_fontes_json_e_json_valido():
    for arquivo in FIXTURES.glob("*/fontes.json"):
        dados = json.loads(arquivo.read_text(encoding="utf-8"))
        assert dados["fontes"]
        assert dados["version_id"] == arquivo.parent.name
