"""A caixa única: um texto solto vira a versão certa, com o ano certo.

Cada teste aqui nasceu de uma frase do pedido de 13/09/2026. O caso "S10 High" e o caso
"raptor 2025" são literais do pedido; os outros são as bordas que eles implicam.
"""

from __future__ import annotations

import json
from typing import Any, ClassVar

import pytest

from pipeline.sugestao import (
    AnoDisponivel,
    Linha,
    alvo_de_pesquisa,
    desempatar,
    separar_ano,
    sugerir,
)


class _Dublê:
    """Chamável com a assinatura de `litellm.completion`, e um contador de chamadas.

    O contador não é enfeite: *"em UMA chamada"* está escrito no pedido, e a forma de um
    desempate por IA virar caro é passar a valer uma chamada por candidato sem ninguém ver.
    """

    def __init__(self, conteudo: dict[str, Any] | Exception):
        self.conteudo = conteudo
        self.chamadas = 0

    def __call__(self, **kwargs: Any) -> Any:
        self.chamadas += 1
        if isinstance(self.conteudo, Exception):
            raise self.conteudo

        class _Mensagem:
            content = json.dumps(self.conteudo, ensure_ascii=False)

        class _Escolha:
            message = _Mensagem()

        class _Uso:
            prompt_tokens = 40
            completion_tokens = 12
            completion_tokens_details = None

        class _Resposta:
            choices: ClassVar = [_Escolha()]
            usage = _Uso()
            finish_reason = "stop"

        return _Resposta()


def _ano(ano: int, *, ficha: bool = True, id_: str | None = None) -> AnoDisponivel:
    return AnoDisponivel(
        ano_modelo=ano,
        version_id=id_ or f"v{ano}",
        in_lineup=True,
        tem_ficha=ficha,
    )


@pytest.fixture
def catalogo() -> list[Linha]:
    """O catálogo da demonstração, com os anos que ele tem de verdade."""
    return [
        Linha("Ford", "Ranger", "Raptor 3.0 V6 Bi-turbo 4WD AT", (_ano(2026, id_="raptor26"),)),
        Linha("Ford", "Ranger", "Limited 3.0 V6 Diesel 4WD AT", (_ano(2027, id_="limited27"),)),
        Linha("Toyota", "Hilux", "SRX Plus AT", (_ano(2026, id_="srx26"),)),
        Linha("Toyota", "Hilux", "GR-Sport", (_ano(2026, ficha=False, id_="gr26"),)),
        Linha("Volkswagen", "Amarok", "V6 Extreme", (_ano(2026, id_="amarok26"),)),
        Linha("Chevrolet", "S10", "High Country", (_ano(2027, id_="s1027"),)),
    ]


class TestOCasoDoPedido:
    def test_s10_high_acha_a_high_country(self, catalogo):
        r = sugerir("S10 High", catalogo)
        assert r.melhor is not None
        assert r.melhor.linha.versao == "High Country"
        assert r.melhor.linha.marca == "Chevrolet"

    def test_s10_high_nao_devolve_as_outras_versoes_como_iguais(self, catalogo):
        """O defeito relatado: achar a High Country e listar **todas** as S10.

        As outras continuam disponíveis — recolhidas, em `outras`. O que não pode é elas
        chegarem à tela com o mesmo peso da encontrada."""
        r = sugerir("S10 High", catalogo)
        assert r.melhor is not None
        assert all(s.linha.versao != "High Country" for s in r.outras)

    def test_hilux_srx_nao_casa_com_a_gr_sport(self, catalogo):
        r = sugerir("hilux srx", catalogo)
        assert r.melhor is not None
        assert r.melhor.linha.versao == "SRX Plus AT"

    def test_amarok_v6_highline_nao_esta_no_catalogo(self, catalogo):
        """Fora do catálogo tem de ser **vazio**, não o primo mais parecido.

        "V6 Highline" não é "V6 Extreme". Devolver a Extreme como acerto seria dizer que
        temos ficha de um carro que ninguém coletou."""
        r = sugerir("amarok v6 highline", catalogo)
        assert r.vazia
        assert r.melhor is None
        assert "limiar" in r.motivo

    def test_raptor_2025_separa_o_ano_e_diz_que_nao_ha_copia(self, catalogo):
        r = sugerir("raptor 2025", catalogo)
        assert r.ano_pedido == 2025
        assert r.melhor is not None
        assert r.melhor.linha.versao.startswith("Raptor")
        assert r.melhor.ano_pedido_sem_ficha == 2025
        assert r.melhor.ano_escolhido is not None
        assert r.melhor.ano_escolhido.ano_modelo == 2026


class TestOAno:
    def test_o_padrao_e_o_mais_recente_com_ficha(self):
        linha = Linha(
            "Ford",
            "Ranger",
            "Raptor",
            (_ano(2024), _ano(2026), _ano(2027, ficha=False)),
        )
        r = sugerir("ranger raptor", [linha])
        assert r.melhor is not None
        assert r.melhor.ano_escolhido is not None
        assert r.melhor.ano_escolhido.ano_modelo == 2026, "2027 existe mas não tem ficha"

    def test_ano_pedido_com_ficha_vence_o_mais_recente(self):
        linha = Linha("Ford", "Ranger", "Raptor", (_ano(2024), _ano(2026)))
        r = sugerir("ranger raptor 2024", [linha])
        assert r.melhor is not None
        assert r.melhor.ano_escolhido is not None
        assert r.melhor.ano_escolhido.ano_modelo == 2024
        assert r.melhor.ano_pedido_sem_ficha is None

    def test_sem_nenhum_ano_com_ficha_ainda_devolve_o_mais_recente(self):
        """Para a tela poder dizer *"não temos cópia"* — e não ficar muda."""
        linha = Linha("Ford", "Ranger", "Raptor", (_ano(2026, ficha=False),))
        r = sugerir("ranger raptor", [linha])
        assert r.melhor is not None
        assert r.melhor.ano_escolhido is not None
        assert r.melhor.ano_escolhido.tem_ficha is False

    def test_anos_com_ficha_lista_so_os_que_tem(self):
        linha = Linha("Ford", "Ranger", "Raptor", (_ano(2024), _ano(2026, ficha=False)))
        assert linha.anos_com_ficha == (2024,)


class TestSepararAno:
    @pytest.mark.parametrize(
        ("entrada", "texto", "ano"),
        [
            ("raptor 2025", "raptor", 2025),
            ("S10 High", "S10 High", None),
            ("hilux srx 2026", "hilux srx", 2026),
            ("ranger", "ranger", None),
            ("amarok v6", "amarok v6", None),
            ("s10 high country 2027", "s10 high country", 2027),
        ],
    )
    def test_o_numero_do_nome_nao_vira_ano(self, entrada, texto, ano):
        """`S10` tem número e não é ano; `2025` é. A diferença é a faixa, não o dígito."""
        assert separar_ano(entrada) == (texto, ano)


class TestBordas:
    def test_consulta_vazia_nao_sugere_nada(self, catalogo):
        r = sugerir("   ", catalogo)
        assert r.vazia
        assert r.motivo == "consulta vazia"

    def test_catalogo_vazio_nao_quebra(self):
        r = sugerir("ranger raptor", [])
        assert r.vazia
        assert r.total == 0

    def test_empate_nao_elege_ninguem_e_diz_quantos(self):
        """Duas versões idênticas ao pedido: a regra não escolhe, e isso é projeto."""
        linhas = [
            Linha("Toyota", "Hilux", "SRX", (_ano(2026, id_="a"),)),
            Linha("Toyota", "Hilux", "SRX", (_ano(2026, id_="b"),)),
        ]
        r = sugerir("hilux srx", linhas)
        assert r.ambigua
        assert r.melhor is None
        assert len(r.empatadas) == 2
        assert "empataram" in r.motivo

    def test_o_limite_corta_outras_e_nao_a_melhor(self, catalogo):
        r = sugerir("ranger raptor", catalogo, limite=1)
        assert r.melhor is not None
        assert len(r.outras) <= 1

    def test_so_a_marca_e_o_modelo_e_ambiguo_de_propósito(self, catalogo):
        """*"ford ranger"* não escolhe entre Raptor e Limited — e não deve.

        As duas cobrem o pedido inteiro e pontuam igual. Eleger uma seria chutar qual
        picape o vendedor quis, com o cliente na frente dele."""
        r = sugerir("ford ranger", catalogo)
        assert r.ambigua
        assert {s.linha.versao for s in r.empatadas} == {
            "Raptor 3.0 V6 Bi-turbo 4WD AT",
            "Limited 3.0 V6 Diesel 4WD AT",
        }

    def test_outras_vem_ordenadas_por_cobertura(self, catalogo):
        r = sugerir("ranger", catalogo)
        coberturas = [s.cobertura for s in r.outras]
        assert coberturas == sorted(coberturas, reverse=True)

    def test_a_melhor_nunca_se_repete_em_outras(self, catalogo):
        r = sugerir("s10 high country", catalogo)
        assert r.melhor is not None
        ids = {s.linha.texto for s in r.outras}
        assert r.melhor.linha.texto not in ids


class TestDesempatePorIA:
    """A IA entra **só** no empate, **uma** vez, e sempre fica marcada como tal.

    O dublê tem a assinatura de `litellm.completion`: nada sai para a rede, e o contador
    de chamadas é a parte que interessa — "uma chamada" é requisito, não detalhe.
    """

    @pytest.fixture
    def empatadas(self):
        return [
            Linha("Toyota", "Hilux", "SRX Plus AT", (_ano(2026, id_="a"),)),
            Linha("Toyota", "Hilux", "SRX Plus 4x4", (_ano(2026, id_="b"),)),
        ]

    @pytest.fixture
    def com_chave(self, monkeypatch):
        monkeypatch.setenv("LLM_FAKE", "0")
        monkeypatch.setenv("LLM_PROVIDER", "gemini")
        monkeypatch.setenv("LLM_MODEL", "gemini-3.6-flash")
        monkeypatch.setenv("GEMINI_API_KEY", "chave-de-teste-nao-e-segredo")

    def test_sem_empate_a_ia_nem_e_chamada(self, catalogo):
        chamadas = []
        r = sugerir("s10 high country", catalogo)
        depois = desempatar(r, cliente=lambda **kw: chamadas.append(kw))
        assert depois is r
        assert chamadas == []

    def test_sem_chave_o_empate_continua_de_pe(self, empatadas, monkeypatch):
        monkeypatch.setenv("LLM_FAKE", "1")
        r = desempatar(sugerir("hilux srx plus", empatadas))
        assert r.ambigua
        assert r.desempate == "regra"
        assert "sem chave" in r.motivo

    def test_a_ia_desfaz_o_empate_em_uma_chamada(self, empatadas, com_chave):
        antes = sugerir("hilux srx plus", empatadas)
        # O índice é o da lista **que foi ao modelo** — a ordem do ranqueador, não a da
        # entrada. Fixar 0 ou 1 aqui travaria o teste numa ordenação que é detalhe.
        alvo = next(i for i, s in enumerate(antes.empatadas) if s.linha.versao == "SRX Plus 4x4")
        dublê = _Dublê({"escolhida": alvo, "porque": "pediu tração 4x4"})
        r = desempatar(antes, cliente=dublê)
        assert dublê.chamadas == 1, "o desempate é UMA chamada, nunca uma por candidato"
        assert r.melhor is not None
        assert r.melhor.linha.versao == "SRX Plus 4x4"
        assert r.desempate == "ia"
        assert "pediu tração 4x4" in r.motivo

    def test_a_perdedora_nao_some_da_tela(self, empatadas, com_chave):
        antes = sugerir("hilux srx plus", empatadas)
        vencedora = antes.empatadas[0].linha.versao
        r = desempatar(antes, cliente=_Dublê({"escolhida": 0}))
        assert r.melhor is not None
        assert r.melhor.linha.versao == vencedora
        assert [s.linha.versao for s in r.outras] == [s.linha.versao for s in antes.empatadas[1:]]

    def test_indice_fora_da_lista_mantem_o_empate(self, empatadas, com_chave):
        """`-1` é o combinado para *"nenhuma das opções"* — e 7 é erro do modelo.

        Nos dois casos o empate fica: duas opções na tela é melhor que uma errada em
        destaque."""
        for chute in (-1, 7, "duas", None):
            r = desempatar(
                sugerir("hilux srx plus", empatadas), cliente=_Dublê({"escolhida": chute})
            )
            assert r.ambigua, f"índice {chute!r} não devia eleger ninguém"
            assert r.desempate == "regra"

    def test_provedor_fora_do_ar_mantem_o_empate(self, empatadas, com_chave):
        r = desempatar(
            sugerir("hilux srx plus", empatadas),
            cliente=_Dublê(RuntimeError("503 overloaded")),
        )
        assert r.ambigua
        assert "não respondeu" in r.motivo


class TestAlvoDePesquisa:
    """A frase digitada vira o trio que o Pesquisador aceita — sem estragar a marca."""

    def test_o_quase_acerto_da_a_marca_e_o_modelo(self, catalogo):
        """O caso que motivou a função. *"amarok v6 highline"* não está no catálogo, mas
        casa dois terços da Amarok V6 Extreme — e é de lá que sai "Volkswagen"."""
        alvo = alvo_de_pesquisa(sugerir("amarok v6 highline", catalogo))
        assert alvo.marca == "Volkswagen"
        assert alvo.modelo == "Amarok"
        assert alvo.versao == "v6 highline"
        assert alvo.de_onde == "catalogo"

    def test_a_marca_e_o_modelo_digitados_nao_se_repetem_na_versao(self, catalogo):
        alvo = alvo_de_pesquisa(sugerir("volkswagen amarok v6 highline", catalogo))
        assert alvo.marca == "Volkswagen"
        assert alvo.versao == "v6 highline", "a marca digitada não volta como parte da versão"

    def test_o_ano_nao_vaza_para_a_versao(self, catalogo):
        alvo = alvo_de_pesquisa(sugerir("amarok v6 highline 2025", catalogo))
        assert "2025" not in alvo.versao

    def test_sem_nenhum_quase_acerto_parte_a_frase_e_admite_o_chute(self, catalogo):
        alvo = alvo_de_pesquisa(sugerir("byd shark gl", catalogo))
        assert (alvo.marca, alvo.modelo, alvo.versao) == ("byd", "shark", "gl")
        assert alvo.de_onde == "texto", "a tela precisa saber que isto é chute, não catálogo"

    def test_uma_palavra_so_nao_quebra(self, catalogo):
        alvo = alvo_de_pesquisa(sugerir("montana", catalogo))
        assert alvo.marca == "montana"
        assert alvo.modelo == ""

    def test_com_acerto_a_versao_do_catalogo_preenche_a_sobra_vazia(self, catalogo):
        """*"chevrolet s10"* casa, e não sobra nada para ser a versão. Mandar versão
        vazia ao Pesquisador faria ele procurar o modelo inteiro; a versão casada é a
        resposta melhor."""
        alvo = alvo_de_pesquisa(sugerir("chevrolet s10", catalogo))
        assert alvo.marca == "Chevrolet"
        assert alvo.versao == "High Country"
