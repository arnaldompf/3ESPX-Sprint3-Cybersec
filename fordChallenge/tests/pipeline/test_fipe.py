"""WP-13 — conector FIPE: código, preço e a referência mensal que os valida.

A regra que organiza este arquivo: **preço sem referência não é preço**. `ConsultaFipe.ok`
exige as duas coisas, e há teste para cada caminho que poderia devolver um preço solto.
"""

from __future__ import annotations

import json
from typing import ClassVar

import pytest

from pipeline.connectors import fipe
from pipeline.connectors.fipe import (
    LIMITE_DIARIO,
    TIER_FIPE,
    ConsultaFipe,
    base_url,
    find_code,
    parse_pagina_fipe,
    parse_resposta_api,
    price,
    referencia_iso,
    requisicoes_do_dia,
)

# --------------------------------------------------------------------- referência
CODIGO_RAPTOR = "003506-8"
CODIGO_AMAROK = "005506-9"
CODIGO_HILUX = "002215-2"
CODIGO_S10 = "004464-4"


@pytest.fixture
def replay(monkeypatch):
    """`REPLAY_MODE=1` explícito. É o padrão da suíte, mas aqui é o assunto do teste."""
    monkeypatch.setenv("REPLAY_MODE", "1")


@pytest.fixture
def snapshot_fipe_amarok(raiz):
    """A página de referência FIPE realmente salva na coleta."""
    caminho = next(
        (raiz / "tests" / "fixtures" / "snapshots").glob(
            "vw_amarok_v6_extreme_2026/*/fipe_amarok/page.md"
        )
    )
    return caminho.read_text(encoding="utf-8")


class TestReferenciaIso:
    @pytest.mark.parametrize(
        ("mes", "ano", "esperado"),
        [
            ("Setembro", 2026, "2026-09"),
            ("setembro", "2026", "2026-09"),
            ("MARÇO", 2026, "2026-03"),
            ("marco", 2026, "2026-03"),
            ("dezembro", 2025, "2025-12"),
        ],
    )
    def test_mes_em_portugues_vira_aaaa_mm(self, mes, ano, esperado):
        assert referencia_iso(mes, ano) == esperado

    def test_mes_desconhecido_levanta_em_vez_de_chutar(self):
        # Chutar o mês aqui produziria um preço com validade errada, que é pior que
        # nenhum preço: o número parece bom e está datado de outro mês.
        with pytest.raises(ValueError, match="desconhecido"):
            referencia_iso("brumário", 2026)


class TestConsultaFipeOk:
    def test_preco_sem_referencia_nao_esta_ok(self):
        assert not ConsultaFipe(preco_brl=452540).ok

    def test_referencia_sem_preco_nao_esta_ok(self):
        assert not ConsultaFipe(referencia="2026-09").ok

    def test_preco_com_referencia_esta_ok(self):
        assert ConsultaFipe(preco_brl=452540, referencia="2026-09").ok

    def test_tier_padrao_e_o_do_tipo_de_fonte(self):
        assert ConsultaFipe().tier == TIER_FIPE == 2


# ------------------------------------------------------- parse da página salva
PAGINA_AMAROK = """# Tabela FIPE Volkswagen AMAROK Extreme CD 2026: R$ 339.270

Marca:\tVW - VolksWagen
Código FIPE:\t005506-9
Ano:\t2026 Diesel
Referência FIPE:\tSetembro de 2026
Preço:\tR$ 339.270,00
"""


class TestParsePaginaFipe:
    def test_le_os_quatro_campos_do_bloco_estruturado(self):
        c = parse_pagina_fipe(PAGINA_AMAROK, url="https://exemplo/fipe")
        assert (c.codigo, c.preco_brl, c.referencia) == ("005506-9", 339270, "2026-09")
        assert (c.ano_modelo, c.combustivel) == (2026, "diesel")
        assert c.modelo_fipe == "Volkswagen AMAROK Extreme CD 2026"
        assert c.ok

    def test_pagina_real_do_snapshot(self, snapshot_fipe_amarok):
        c = parse_pagina_fipe(snapshot_fipe_amarok)
        assert (c.codigo, c.preco_brl, c.referencia) == ("005506-9", 339270, "2026-09")

    def test_pagina_sem_bloco_reprova_com_motivo_dizendo_o_que_falta(self):
        c = parse_pagina_fipe("Página de erro 404. Nada aqui.")
        assert not c.ok
        assert "sem preço" in c.motivo and "sem referência" in c.motivo

    def test_preco_sem_referencia_reprova(self):
        # O caso perigoso: há um número, e ele é o número certo. Falta a validade.
        c = parse_pagina_fipe("Código FIPE:\t005506-9\nPreço:\tR$ 339.270,00")
        assert c.preco_brl == 339270
        assert not c.ok
        assert "referência" in c.motivo

    def test_mes_invalido_na_pagina_vira_motivo_nao_excecao(self):
        c = parse_pagina_fipe("Referência FIPE:\tBrumário de 2026\nPreço:\tR$ 1.000,00")
        assert not c.ok
        assert "desconhecido" in c.motivo


# ------------------------------------------------------------ price() em replay
@pytest.mark.usefixtures("replay")
class TestPriceEmReplay:
    def test_criterio_de_aceite_codigo_003506_8_com_referencia_2026_09(self):
        """Critério de aceite da spec, com o valor do gabarito."""
        c = price(CODIGO_RAPTOR)
        assert c.referencia == "2026-09"
        assert c.preco_brl == 452540
        assert c.ok

    def test_amarok_vem_da_captura_da_pagina(self):
        c = price(CODIGO_AMAROK, 2026)
        assert (c.preco_brl, c.referencia, c.ano_modelo) == (339270, "2026-09", 2026)
        assert "página de referência" in c.origem

    def test_snapshot_da_api_declara_a_proveniencia(self):
        # A coleta de 2026-09-10 salvou a resposta da API FIPE do Raptor. A origem tem
        # de dizer **isto**, e não "página de referência": as duas são fontes FIPE, mas
        # não são a mesma coisa, e a proveniência viaja com o valor.
        c = price(CODIGO_RAPTOR)
        assert c.origem == "snapshot da resposta da API FIPE"
        assert c.source_id == "fipe_raptor"

    def test_tier_e_do_tipo_de_fonte_nao_do_documento(self):
        # O `meta.tier` do registro do Raptor é 1. Herdá-lo inflaria a confiança de um
        # valor de mercado — e para cima, que é o lado que engana.
        c = price(CODIGO_RAPTOR)
        assert c.tier == TIER_FIPE == 2

    def test_s10_e_hilux_agora_tem_fonte_salva(self):
        # Estes dois eram os buracos do eval: código conhecido, valor em lugar nenhum.
        # A coleta de 2026-09-10 salvou a resposta da API, e o valor bate com o
        # gabarito v1 (294.378 para a S10). O que era `nao_encontrado` virou dado.
        s10 = price(CODIGO_S10)
        assert (s10.preco_brl, s10.referencia) == (294378, "2026-09")
        assert s10.quote_preco == '"Valor":"R$ 294.378,00"'

        hilux = price(CODIGO_HILUX)
        assert (hilux.preco_brl, hilux.referencia) == (317511, "2026-09")

    def test_codigo_sem_fonte_salva_nao_cai_na_rede(self):
        # A invariante continua: **sem** fonte salva, replay não sai para a internet.
        # O código é válido no formato e não existe em snapshot nenhum.
        c = price("999999-9")
        assert not c.ok
        assert "REPLAY_MODE=1" in c.motivo

    def test_codigo_fora_do_formato_nao_gasta_requisicao(self):
        antes = requisicoes_do_dia()
        c = price("HILUX 2.8")
        assert not c.ok
        assert "formato" in c.motivo
        assert requisicoes_do_dia() == antes

    def test_ano_divergente_descarta_a_fonte(self):
        c = price(CODIGO_AMAROK, 2019)
        assert not c.ok


# --------------------------------------------------------------- resposta da API
RESPOSTA_API = json.dumps(
    {
        "Valor": "R$ 452.540,00",
        "Marca": "Ford",
        "Modelo": "RANGER RAPTOR 3.0 V6 BI-TURBO 4WD AUT.",
        "AnoModelo": 2026,
        "Combustivel": "Gasolina",
        "CodigoFipe": "003506-8",
        "MesReferencia": "setembro de 2026 ",
        "TipoVeiculo": 1,
        "SiglaCombustivel": "G",
    },
    ensure_ascii=False,
)


class TestParseRespostaApi:
    def test_le_valor_referencia_e_metadados(self):
        c = parse_resposta_api(RESPOSTA_API, url="https://api/fipe")
        assert (c.preco_brl, c.referencia, c.ano_modelo) == (452540, "2026-09", 2026)
        assert (c.codigo, c.combustivel) == ("003506-8", "gasolina")
        assert c.ok

    def test_resposta_sem_referencia_reprova(self):
        c = parse_resposta_api(json.dumps({"Valor": "R$ 452.540,00"}))
        assert c.preco_brl == 452540
        assert not c.ok

    def test_referencia_em_formato_desconhecido_vira_motivo(self):
        c = parse_resposta_api(json.dumps({"Valor": "R$ 1,00", "MesReferencia": "13/2026"}))
        assert not c.ok
        assert "formato desconhecido" in c.motivo

    def test_corpo_que_nao_e_json_vira_motivo(self):
        c = parse_resposta_api("<html>502 Bad Gateway</html>")
        assert not c.ok
        assert "não é JSON" in c.motivo

    def test_lista_em_vez_de_objeto_vira_motivo(self):
        c = parse_resposta_api("[]")
        assert not c.ok
        assert "não é um objeto" in c.motivo


# ------------------------------------------------------------------ limite diário
class TestLimiteDiario:
    def test_teto_alcancado_nao_faz_a_consulta(self, monkeypatch, tmp_path):
        monkeypatch.setenv("REPLAY_MODE", "0")
        monkeypatch.setattr(fipe, "CACHE_FIPE", tmp_path)
        monkeypatch.setattr(fipe, "_consulta_de_snapshot", lambda *a, **k: None)
        (tmp_path / f"requisicoes_{fipe._dia_de_hoje()}.json").write_text(
            json.dumps({"total": LIMITE_DIARIO}), encoding="utf-8"
        )

        def nunca(*a, **k):  # pragma: no cover - falha o teste se chamado
            raise AssertionError("o limite diário tinha de impedir a requisição")

        monkeypatch.setattr("pipeline.fetch.http.fetch", nunca)
        c = price(CODIGO_RAPTOR)
        assert not c.ok
        assert str(LIMITE_DIARIO) in c.motivo

    def test_contador_persiste_entre_processos(self, monkeypatch, tmp_path):
        monkeypatch.setattr(fipe, "CACHE_FIPE", tmp_path)
        dia = "2026-09-08"
        assert requisicoes_do_dia(dia) == 0
        fipe._registra_requisicao(dia)
        fipe._registra_requisicao(dia)
        # Ler do disco é o ponto: um contador em memória zeraria a cada execução e o
        # teto de 500/dia da API viraria decorativo.
        assert requisicoes_do_dia(dia) == 2
        assert requisicoes_do_dia("2026-09-09") == 0

    def test_contador_corrompido_conta_zero_em_vez_de_explodir(self, monkeypatch, tmp_path):
        monkeypatch.setattr(fipe, "CACHE_FIPE", tmp_path)
        dia = "2026-09-08"
        (tmp_path / f"requisicoes_{dia}.json").write_text("{lixo", encoding="utf-8")
        assert requisicoes_do_dia(dia) == 0


class TestBaseUrl:
    def test_vem_de_env_porque_a_api_muda_de_host(self, monkeypatch):
        monkeypatch.setenv("FIPE_BASE_URL", "https://outro.host/fipe/api/v1/")
        assert base_url() == "https://outro.host/fipe/api/v1"

    def test_sem_env_usa_o_padrao(self, monkeypatch):
        monkeypatch.delenv("FIPE_BASE_URL", raising=False)
        assert base_url() == fipe.FIPE_BASE_URL_PADRAO


# ------------------------------------------------------------------- find_code
@pytest.mark.usefixtures("replay")
class TestFindCode:
    #: A lista que a API devolve para "Hilux": o nome longo é o da FIPE, não o do catálogo.
    MODELOS_FIPE: ClassVar[dict[str, str]] = {
        "HILUX CD SRX PLUS 4X4 2.8 TDI Die. Aut.": "002215-2",
        "HILUX CD SRX 4X4 2.8 TDI 16V Die. Aut.": "002214-4",
        "HILUX CD SR 4X4 2.8 TDI 16V Die. Aut.": "002213-6",
        "HILUX CS Chassi 4X4 3.0 TDI Die.": "002133-4",
    }

    def test_criterio_de_aceite_hilux_srx_plus_resolve_002215_2(self):
        r = find_code("Toyota", "Hilux", "SRX Plus AT", modelos_fipe=self.MODELOS_FIPE)
        assert r.codigo == "002215-2"
        assert r.ok

    def test_srx_ambiguo_entre_srx_e_srx_plus_nao_escolhe_em_silencio(self):
        # O outro lado da moeda do subconjunto: pedir "SRX AT" cobre inteiramente tanto
        # "SRX" quanto "SRX Plus", e a cobertura da consulta não distingue os dois. O
        # sistema **não escolhe**: devolve as duas alternativas e o motivo. Errar aqui
        # colocaria o preço da Plus na SRX sem ninguém notar.
        r = find_code("Toyota", "Hilux", "SRX AT", modelos_fipe=self.MODELOS_FIPE)
        assert not r.ok
        assert "não escolhe em silêncio" in r.motivo
        assert len(r.alternativas) == 2
        assert all("SRX" in nome for nome in r.alternativas)

    def test_catalogo_tem_precedencia_sobre_o_fuzzy(self):
        r = find_code(
            "Toyota",
            "Hilux",
            "SRX Plus AT",
            modelos_fipe=self.MODELOS_FIPE,
            catalogo={"Hilux SRX Plus AT": "999999-9"},
        )
        assert r.codigo == "999999-9"
        assert "catálogo" in r.origem

    def test_versao_inexistente_devolve_motivo_e_alternativas(self):
        r = find_code("Toyota", "Hilux", "GR Sport Hybrid", modelos_fipe=self.MODELOS_FIPE)
        assert not r.ok
        assert r.motivo
