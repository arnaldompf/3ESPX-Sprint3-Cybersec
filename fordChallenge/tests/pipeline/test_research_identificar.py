"""De um texto solto ao carro certo — perguntando quando não dá para saber.

O que este arquivo fixa, na ordem da economia do módulo: o catálogo responde de graça; a
busca só entra quando o catálogo não responde; o modelo só organiza o que a busca trouxe —
e **opção sem fonte cai antes da tela**. O ano nunca vira pergunta: vale o do texto, senão o
das fontes, senão o vigente, e a resposta diz qual foi.

Nada aqui toca a rede: a busca é dublada e o `completion` é um chamável de teste.
"""

from __future__ import annotations

import json
from typing import ClassVar

import pytest

from pipeline import sugestao
from pipeline.research import identificar, search

URL_1 = "https://www.mobiauto.com.br/catalogo/mitsubishi/triton/2026"
URL_2 = "https://www.mitsubishimotors.com.br/veiculos/triton"
URL_3 = "https://quatrorodas.abril.com.br/noticias/triton-2026-versoes"


def _linha(marca: str, modelo: str, versao: str, *, ano: int = 2026, ficha: bool = True):
    return sugestao.Linha(
        marca=marca,
        modelo=modelo,
        versao=versao,
        anos=(
            sugestao.AnoDisponivel(
                ano_modelo=ano,
                version_id=f"v-{versao.lower().replace(' ', '-')}",
                codigo_fipe=None,
                in_lineup=True,
                tem_ficha=ficha,
            ),
        ),
    )


CATALOGO = [
    _linha("Ford", "Ranger", "Raptor 3.0 V6 Bi-turbo 4WD AT"),
    _linha("Ford", "Ranger", "Limited 3.0 V6 Diesel 4WD AT", ficha=False),
    _linha("Toyota", "Hilux", "SR"),
    _linha("Toyota", "Hilux", "SRV"),
]


@pytest.fixture
def modelo_ligado(monkeypatch: pytest.MonkeyPatch):
    """Chave de mentira e modo fake desligado: o módulo passa a considerar buscar e chamar."""
    monkeypatch.setenv("LLM_FAKE", "0")
    monkeypatch.setenv("LLM_PROVIDER", "kimi")
    monkeypatch.setenv("LLM_MODEL", "kimi-k2.6")
    monkeypatch.setenv("LLM_API_KEY", "placeholder-de-teste")


@pytest.fixture
def busca_dublada(monkeypatch: pytest.MonkeyPatch):
    """`search.buscar` devolve as URLs combinadas e registra as consultas feitas."""
    estado = {"urls": [URL_1, URL_2, URL_3], "consultas": [], "erro": None}

    def falso(consulta, *, provedor="", quantos=10):
        estado["consultas"].append(consulta)
        if estado["erro"] is not None:
            raise estado["erro"]
        achados = [
            search.Achado(
                url=url,
                titulo=f"Mitsubishi Triton 2026: versões e ficha técnica ({i})",
                snippet="HPE-S, Katana e Sport",
                posicao=i,
                provedor="dublado",
                consulta=consulta,
            )
            for i, url in enumerate(estado["urls"])
        ]
        return search.Resposta(consulta=consulta, provedor="dublado", achados=achados)

    monkeypatch.setattr(search, "buscar", falso)
    return estado


def _cliente(resposta: dict):
    """Um `completion` de teste que devolve o JSON combinado e conta as chamadas."""
    chamadas: list[dict] = []

    def falso(**kwargs):
        chamadas.append(kwargs)
        return {
            "choices": [{"message": {"content": json.dumps(resposta, ensure_ascii=False)}}],
            "usage": {"prompt_tokens": 500, "completion_tokens": 120},
        }

    falso.chamadas = chamadas  # type: ignore[attr-defined]
    return falso


RESPOSTA_TRITON = {
    "marca": "Mitsubishi",
    "modelo": "Triton",
    "versao": "",
    "ano_modelo": None,
    "modelos": [],
    "versoes": [
        {"nome": "HPE-S", "detalhe": "topo de linha, 2.4 diesel", "fonte": 1, "ano": None},
        {"nome": "Katana", "detalhe": "aventureira", "fonte": 2, "ano": None},
        {"nome": "Inventada", "detalhe": "sem fonte", "fonte": 99, "ano": None},
        {"nome": "Sport", "detalhe": "entrada", "fonte": "x", "ano": None},
    ],
    "pergunta": "Qual versão da Triton você quer?",
}


class TestOCatalogoRespondePrimeiro:
    def test_resolve_sem_busca_e_sem_modelo(self, modelo_ligado, busca_dublada):
        cliente = _cliente(RESPOSTA_TRITON)
        r = identificar.identificar("Ranger Raptor", catalogo=CATALOGO, cliente=cliente)
        assert r.estado == identificar.RESOLVIDO
        assert (r.marca, r.modelo) == ("Ford", "Ranger")
        assert r.versao.startswith("Raptor")
        assert r.version_id == "v-raptor-3.0-v6-bi-turbo-4wd-at" and r.tem_ficha
        assert r.ano == 2026 and r.ano_origem == identificar.ANO_DO_CATALOGO
        assert busca_dublada["consultas"] == [] and cliente.chamadas == []

    def test_empate_no_catalogo_vira_pergunta_sem_gastar_nada(self, modelo_ligado, busca_dublada):
        cliente = _cliente(RESPOSTA_TRITON)
        r = identificar.identificar("hilux", catalogo=CATALOGO, cliente=cliente)
        assert r.estado == identificar.PRECISA_ESCOLHER
        assert {o.valor for o in r.opcoes} == {"SR", "SRV"}
        assert all(o.marca == "Toyota" and o.modelo == "Hilux" for o in r.opcoes)
        assert busca_dublada["consultas"] == [] and cliente.chamadas == []

    def test_a_versao_sem_ficha_tambem_resolve_e_diz_que_nao_tem_ficha(self, modelo_ligado):
        r = identificar.identificar("Ranger Limited", catalogo=CATALOGO, cliente=_cliente({}))
        assert r.estado == identificar.RESOLVIDO
        assert r.tem_ficha is False and r.version_id


class TestABuscaEOModelo:
    def test_opcoes_so_com_fonte(self, modelo_ligado, busca_dublada):
        r = identificar.identificar("Triton", cliente=_cliente(RESPOSTA_TRITON))
        assert r.estado == identificar.PRECISA_ESCOLHER
        assert [o.valor for o in r.opcoes] == ["HPE-S", "Katana"], "opção sem fonte chegou à tela"
        assert r.opcoes[0].fontes == (URL_1,) and r.opcoes[1].fontes == (URL_2,)
        assert all(o.tipo == "versao" and o.modelo == "Triton" for o in r.opcoes)
        assert r.pergunta == "Qual versão da Triton você quer?"
        assert r.origem == "busca" and r.uso["chamadas"] == 1

    def test_ate_tres_consultas_deduplicadas(self, modelo_ligado, busca_dublada):
        busca_dublada["urls"] = [URL_1, URL_1, URL_2]
        r = identificar.identificar("Triton", cliente=_cliente(RESPOSTA_TRITON))
        assert len(busca_dublada["consultas"]) == 3
        assert busca_dublada["consultas"][0] == "Triton versões ficha técnica"
        assert "site oficial" in busca_dublada["consultas"][2]
        assert list(r.fontes) == [URL_1, URL_2]
        assert list(r.consultas) == busca_dublada["consultas"]

    def test_o_teto_de_resultados_vale(self, modelo_ligado, busca_dublada):
        busca_dublada["urls"] = [f"https://exemplo.com.br/{i}" for i in range(20)]
        cliente = _cliente(RESPOSTA_TRITON)
        identificar.identificar("Triton", cliente=cliente)
        prompt = cliente.chamadas[0]["messages"][1]["content"]
        assert f"[{identificar.RESULTADOS_NA_BUSCA}]" in prompt
        assert f"[{identificar.RESULTADOS_NA_BUSCA + 1}]" not in prompt

    def test_versao_ja_dita_resolve_direto(self, modelo_ligado, busca_dublada):
        resposta = {**RESPOSTA_TRITON, "versao": "HPE-S"}
        r = identificar.identificar("Triton HPE-S", cliente=_cliente(resposta))
        assert r.estado == identificar.RESOLVIDO
        assert (r.marca, r.modelo, r.versao) == ("Mitsubishi", "Triton", "HPE-S")

    def test_nenhuma_versao_com_fonte_e_nao_entendi(self, modelo_ligado, busca_dublada):
        resposta = {**RESPOSTA_TRITON, "versoes": [{"nome": "X", "fonte": 42}]}
        r = identificar.identificar("Triton", cliente=_cliente(resposta))
        assert r.estado == identificar.NAO_ENTENDI
        assert "nenhuma versão saiu dos resultados com fonte" in r.motivo

    def test_busca_fora_do_ar_e_nao_entendi_com_motivo(self, modelo_ligado, busca_dublada):
        busca_dublada["erro"] = RuntimeError("tavily fora do ar")
        cliente = _cliente(RESPOSTA_TRITON)
        r = identificar.identificar("Triton", cliente=cliente)
        assert r.estado == identificar.NAO_ENTENDI
        assert "tavily fora do ar" in r.motivo
        assert cliente.chamadas == [], "sem resultado, o modelo não é chamado"

    def test_uma_consulta_fora_do_ar_nao_derruba_as_outras(self, modelo_ligado, busca_dublada):
        original_erro = RuntimeError("timeout")
        vez = {"n": 0}
        original = search.buscar

        def falha_na_primeira(consulta, **kw):
            vez["n"] += 1
            if vez["n"] == 1:
                raise original_erro
            return original(consulta, **kw)

        search.buscar = falha_na_primeira
        r = identificar.identificar("Triton", cliente=_cliente(RESPOSTA_TRITON))
        assert r.estado == identificar.PRECISA_ESCOLHER

    def test_modelo_que_falha_e_nao_entendi_e_diz(self, modelo_ligado, busca_dublada):
        def explode(**_):
            raise RuntimeError("provedor caiu")

        r = identificar.identificar("Triton", cliente=explode)
        assert r.estado == identificar.NAO_ENTENDI
        assert "o modelo não" in r.motivo and "provedor caiu" in r.motivo


class TestOAno:
    def test_o_ano_do_texto_vence_e_vai_para_a_busca(self, modelo_ligado, busca_dublada):
        resposta = {**RESPOSTA_TRITON, "ano_modelo": 2027}
        r = identificar.identificar("Triton 2025", cliente=_cliente(resposta))
        assert (r.ano, r.ano_origem) == (2025, identificar.ANO_DO_PEDIDO)
        assert any("2025" in c for c in busca_dublada["consultas"])
        assert not any("2027" in c for c in busca_dublada["consultas"])

    def test_o_parametro_ano_sobrepoe_o_texto(self, modelo_ligado, busca_dublada):
        r = identificar.identificar("Triton 2025", ano=2024, cliente=_cliente(RESPOSTA_TRITON))
        assert (r.ano, r.ano_origem) == (2024, identificar.ANO_DO_PEDIDO)

    def test_sem_ano_no_texto_vale_o_das_fontes(self, modelo_ligado, busca_dublada):
        resposta = {**RESPOSTA_TRITON, "ano_modelo": 2027}
        r = identificar.identificar("Triton", cliente=_cliente(resposta))
        assert (r.ano, r.ano_origem) == (2027, identificar.ANO_DAS_FONTES)

    def test_sem_ano_em_lugar_nenhum_assume_o_vigente_e_diz(self, modelo_ligado, busca_dublada):
        r = identificar.identificar("Triton", cliente=_cliente(RESPOSTA_TRITON))
        assert (r.ano, r.ano_origem) == (identificar.ano_vigente(), identificar.ANO_VIGENTE)
        assert r.to_dict()["ano_origem"] == "vigente"

    def test_ano_fora_de_faixa_das_fontes_e_ignorado(self, modelo_ligado, busca_dublada):
        resposta = {**RESPOSTA_TRITON, "ano_modelo": 1200}
        r = identificar.identificar("Triton", cliente=_cliente(resposta))
        assert r.ano_origem == identificar.ANO_VIGENTE


class TestModeloAmbiguo:
    RESPOSTA_RAM: ClassVar[dict] = {
        "marca": "RAM",
        "modelo": "",
        "versao": "",
        "ano_modelo": None,
        "modelos": [
            {"marca": "RAM", "modelo": "Rampage", "fonte": 1},
            {"marca": "RAM", "modelo": "Dakota", "fonte": 2},
            {"marca": "RAM", "modelo": "Inventada", "fonte": 77},
        ],
        "versoes": [],
        "pergunta": "De qual RAM você fala?",
    }

    def test_modelos_ambiguos_viram_chips_de_modelo(self, modelo_ligado, busca_dublada):
        r = identificar.identificar("a picape nova da RAM", cliente=_cliente(self.RESPOSTA_RAM))
        assert r.estado == identificar.PRECISA_ESCOLHER
        assert [o.valor for o in r.opcoes] == ["RAM Rampage", "RAM Dakota"]
        assert all(o.tipo == "modelo" for o in r.opcoes)
        assert r.pergunta == "De qual RAM você fala?"

    def test_um_modelo_so_nao_e_pergunta(self, modelo_ligado, busca_dublada):
        resposta = {
            **self.RESPOSTA_RAM,
            "modelos": [{"marca": "RAM", "modelo": "Rampage", "fonte": 1}],
            "versoes": [{"nome": "Laramie", "detalhe": "", "fonte": 1, "ano": None}],
        }
        r = identificar.identificar("a picape nova da RAM", cliente=_cliente(resposta))
        assert r.modelo == "Rampage"
        assert r.estado == identificar.PRECISA_ESCOLHER
        assert [o.valor for o in r.opcoes] == ["Laramie"] and r.opcoes[0].modelo == "Rampage"


class TestSemModelo:
    def test_pedido_completo_identifica_sem_modelo_e_sem_busca(self, monkeypatch, busca_dublada):
        monkeypatch.setenv("LLM_FAKE", "1")
        r = identificar.identificar("Mitsubishi Triton HPE-S 2.4 Diesel 2026")
        assert r.estado == identificar.RESOLVIDO
        assert (r.marca, r.modelo, r.versao) == (
            "Mitsubishi",
            "Triton",
            "HPE-S 2.4 Diesel",
        )
        assert (r.ano, r.ano_origem, r.origem) == (2026, identificar.ANO_DO_PEDIDO, "pedido")
        assert busca_dublada["consultas"] == []

    def test_LLM_FAKE_nao_busca_e_nao_chama(self, monkeypatch, busca_dublada):
        monkeypatch.setenv("LLM_FAKE", "1")
        cliente = _cliente(RESPOSTA_TRITON)
        r = identificar.identificar("Triton", catalogo=CATALOGO, cliente=cliente)
        assert r.estado == identificar.NAO_ENTENDI
        assert "não há modelo configurado" in r.motivo
        assert busca_dublada["consultas"] == [] and cliente.chamadas == []

    def test_texto_vazio(self):
        r = identificar.identificar("   ")
        assert r.estado == identificar.NAO_ENTENDI and r.origem == "nenhuma"

    def test_to_dict_leva_tudo_que_a_tela_precisa(self, modelo_ligado, busca_dublada):
        d = identificar.identificar("Triton", cliente=_cliente(RESPOSTA_TRITON)).to_dict()
        for chave in (
            "estado",
            "marca",
            "modelo",
            "ano",
            "ano_origem",
            "pergunta",
            "opcoes",
            "fontes",
            "uso",
        ):
            assert chave in d
        assert d["opcoes"][0]["tipo"] == "versao" and d["opcoes"][0]["fontes"] == [URL_1]
