"""O mapa de segmentos: contra quem cada modelo Ford briga.

O que estes testes guardam é menos a leitura do YAML e mais **as três recusas**: modelo
fora do mapa não vira lista vazia, concorrente de categoria diferente não entra sem
motivo, e segmento inexistente não passa em silêncio. As três existem porque o erro neste
módulo não aparece como erro — aparece como uma matriz impecável comparando carros que
ninguém compara.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pipeline.benchmark import segments


@pytest.fixture(autouse=True)
def _sem_cache():
    segments.carregar.cache_clear()
    yield
    segments.carregar.cache_clear()


def _mapa(texto: str, tmp_path: Path):
    arquivo = tmp_path / "segments.yaml"
    arquivo.write_text(texto, encoding="utf-8")
    return segments.carregar(arquivo)


class TestOArquivoDeVerdade:
    def test_a_ranger_e_picape_media(self):
        seg = segments.segmento_de("Ranger")
        assert seg.id == "picape_media"
        assert seg.rotulo == "picape média"

    def test_os_seis_concorrentes_de_verdade_vem_antes_da_toro(self):
        """A ordem é informação: quem lê de cima para baixo encontra primeiro quem briga."""
        nomes = [c.rotulo for c in segments.concorrentes_de("Ranger")]
        assert nomes == [
            "Toyota Hilux",
            "Volkswagen Amarok",
            "Chevrolet S10",
            "RAM Rampage",
            "Mitsubishi Triton",
            "Nissan Frontier",
            "Fiat Toro",
        ]
        assert nomes[-1] == "Fiat Toro", "a de categoria diferente vem por último"

    def test_a_toro_entra_marcada_e_com_motivo(self):
        toro = next(c for c in segments.concorrentes_de("Ranger") if c.modelo == "Toro")
        assert toro.categoria_diferente is True
        assert "monobloco" in toro.motivo

    def test_so_a_toro_esta_marcada(self):
        marcadas = [c.rotulo for c in segments.concorrentes_de("Ranger") if c.categoria_diferente]
        assert marcadas == ["Fiat Toro"]

    def test_o_nome_do_modelo_nao_precisa_bater_maiuscula_e_acento(self):
        assert segments.segmento_de("ranger").id == "picape_media"
        assert segments.segmento_de("  RANGER ").id == "picape_media"

    def test_o_arquivo_tem_versao(self):
        assert segments.carregar().versao == "2026-09-13"


class TestModeloForaDoMapa:
    def test_levanta_em_vez_de_devolver_lista_vazia(self):
        """Lista vazia e "não sei" exigem telas diferentes: uma mostra zero concorrentes,
        a outra mostra o painel de descoberta com as fontes."""
        with pytest.raises(segments.SegmentoDesconhecido):
            segments.segmento_de("Maverick")

    def test_a_consulta_de_descoberta_e_em_portugues(self):
        """Quem escreve sobre concorrência de picape no Brasil escreve em português."""
        assert (
            segments.consulta_de_descoberta("Ford", "Maverick") == "concorrentes da Ford Maverick"
        )

    def test_a_consulta_nao_quebra_sem_marca(self):
        assert segments.consulta_de_descoberta("", "Maverick") == "concorrentes da Maverick"


class TestOArquivoInvalido:
    def test_categoria_diferente_sem_motivo_e_recusada(self, tmp_path):
        """Marca sem motivo é o sistema opinando: a tela exibiria "categoria diferente"
        sem ter o que responder a "por quê?"."""
        with pytest.raises(ValueError, match="sem motivo"):
            _mapa(
                """
versao: teste
segmentos:
  x:
    rotulo: X
    concorrentes:
      - marca: Fiat
        modelo: Toro
        categoria_diferente: true
modelos_ford: {}
""",
                tmp_path,
            )

    def test_segmento_inexistente_no_mapa_de_modelos_e_recusado(self, tmp_path):
        with pytest.raises(ValueError, match="segmento inexistente"):
            _mapa(
                """
versao: teste
segmentos: {}
modelos_ford:
  Ranger: picape_media
""",
                tmp_path,
            )

    def test_concorrente_sem_modelo_e_recusado(self, tmp_path):
        with pytest.raises(ValueError, match="sem marca ou modelo"):
            _mapa(
                """
versao: teste
segmentos:
  x:
    rotulo: X
    concorrentes:
      - marca: Toyota
modelos_ford: {}
""",
                tmp_path,
            )
