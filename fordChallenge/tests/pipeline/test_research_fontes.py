"""O mapa de domínios: o que o arquivo promete, e o que ele recusa.

`fontes.yaml` decide onde a pesquisa procura e o que ela espera achar. Um erro ali é caro e
silencioso: um `tipo` errado faz a coleta gastar página na fonte que rende menos; um tier
errado faz uma matéria vencer a montadora numa divergência. Por isso o carregamento valida
e **levanta com o nome do domínio** — nunca ignora a linha torta.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pipeline.research import fontes


@pytest.fixture(autouse=True)
def _sem_cache():
    """`carregar` é cacheada; cada teste começa com o cache limpo."""
    fontes.carregar.cache_clear()
    yield
    fontes.carregar.cache_clear()


def escrever(tmp_path: Path, corpo: str) -> Path:
    alvo = tmp_path / "fontes.yaml"
    alvo.write_text(corpo, encoding="utf-8")
    return alvo


class TestOArquivoDeVerdade:
    def test_carrega_e_tem_versao(self):
        mapa = fontes.carregar()
        assert mapa.versao, "o arquivo precisa dizer de quando ele é"
        assert len(mapa.fontes) >= 8

    def test_todo_dominio_tem_tier_e_tipo_conhecidos(self):
        for f in fontes.carregar().fontes:
            assert 1 <= f.tier <= 5, f.dominio
            assert f.tipo in fontes.TIPOS, f.dominio

    def test_os_reprovados_dizem_por_que(self):
        """A lista existe tanto para dizer onde procurar quanto para não repetir busca
        que já se provou vazia — e isso só serve com o motivo escrito."""
        reprovados = fontes.carregar().reprovados
        assert "motor1.uol.com.br" in reprovados
        assert "403" in reprovados["motor1.uol.com.br"]
        assert fontes.motivo_da_reprovacao("www.motor1.uol.com.br")

    def test_os_sites_que_a_sondagem_aprovou_estao_como_ficha(self):
        """Os cinco que renderam 12 campos ou mais por regra, medidos em 13/09/2026."""
        for dominio in (
            "icarros.com.br",
            "noticiasautomotivas.com.br",
            "quatrorodas.abril.com.br",
            "carrosegaragem.com.br",
            "carrosnaweb.com.br",
        ):
            fonte = fontes.fonte_de(dominio)
            assert fonte is not None and fonte.tipo == "ficha", dominio

    def test_quem_exige_navegador_esta_marcado(self):
        assert fontes.exige_navegador("www.carrosnaweb.com.br")
        assert fontes.exige_navegador("quatrorodas.abril.com.br")
        assert not fontes.exige_navegador("icarros.com.br")

    def test_ficha_vem_antes_de_imprensa_na_busca_restrita(self):
        ordem = fontes.dominios_de_ficha()
        fichas = [d for d in ordem if fontes.fonte_de(d).tipo == "ficha"]
        imprensas = [d for d in ordem if fontes.fonte_de(d).tipo == "imprensa"]
        assert ordem[: len(fichas)] == fichas, "imprensa apareceu no meio das fichas"
        assert imprensas, "a lista restrita não pode ser só de ficha"
        # Dentro do tipo, o que rendeu mais campos vem primeiro.
        assert ordem[0] == "icarros.com.br"

    def test_subdominio_casa_com_o_dominio_registrado(self):
        assert fontes.fonte_de("www.icarros.com.br") is not None
        assert fontes.fonte_de("m.icarros.com.br") is not None
        assert fontes.fonte_de("naoicarros.com.br") is None

    def test_o_mais_especifico_ganha(self):
        """`autopapo.uol.com.br` e `uol.com.br` estão os dois no arquivo."""
        fonte = fontes.fonte_de("autopapo.uol.com.br")
        assert fonte is not None and fonte.dominio == "autopapo.uol.com.br"


class TestOQueOArquivoRecusa:
    def test_dominio_sem_tier(self, tmp_path):
        caminho = escrever(
            tmp_path, "versao: 2026-09-13\ndominios:\n  - dominio: x.com.br\n    tipo: ficha\n"
        )
        with pytest.raises(fontes.FontesInvalidas, match=r"x\.com\.br.*tier"):
            fontes.carregar(caminho)

    def test_tipo_desconhecido(self, tmp_path):
        caminho = escrever(
            tmp_path,
            "versao: 2026-09-13\ndominios:\n  - dominio: x.com.br\n    tier: 3\n    tipo: blog\n",
        )
        with pytest.raises(fontes.FontesInvalidas, match="blog"):
            fontes.carregar(caminho)

    def test_tier_fora_da_escala(self, tmp_path):
        caminho = escrever(
            tmp_path,
            "versao: 2026-09-13\ndominios:\n  - dominio: x.com.br\n    tier: 9\n    tipo: ficha\n",
        )
        with pytest.raises(fontes.FontesInvalidas, match="fora de 1"):
            fontes.carregar(caminho)

    def test_dominio_repetido(self, tmp_path):
        caminho = escrever(
            tmp_path,
            "versao: 2026-09-13\ndominios:\n"
            "  - dominio: x.com.br\n    tier: 3\n    tipo: ficha\n"
            "  - dominio: x.com.br\n    tier: 3\n    tipo: imprensa\n",
        )
        with pytest.raises(fontes.FontesInvalidas, match="duas vezes"):
            fontes.carregar(caminho)

    def test_reprovado_sem_motivo(self, tmp_path):
        caminho = escrever(
            tmp_path,
            "versao: 2026-09-13\ndominios:\n  - dominio: x.com.br\n    tier: 3\n    tipo: ficha\n"
            "reprovados:\n  - dominio: y.com.br\n",
        )
        with pytest.raises(fontes.FontesInvalidas, match="sem motivo"):
            fontes.carregar(caminho)

    def test_o_mesmo_dominio_aprovado_e_reprovado(self, tmp_path):
        caminho = escrever(
            tmp_path,
            "versao: 2026-09-13\ndominios:\n  - dominio: x.com.br\n    tier: 3\n    tipo: ficha\n"
            "reprovados:\n  - dominio: x.com.br\n    motivo: bloqueia\n",
        )
        with pytest.raises(fontes.FontesInvalidas, match="em `dominios` e em `reprovados`"):
            fontes.carregar(caminho)

    def test_arquivo_sem_dominio_nenhum(self, tmp_path):
        caminho = escrever(tmp_path, "versao: 2026-09-13\ndominios: []\n")
        with pytest.raises(fontes.FontesInvalidas, match="nenhum domínio"):
            fontes.carregar(caminho)
