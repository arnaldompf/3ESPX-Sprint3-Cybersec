"""Os provedores de busca, e a regra que virou assinatura de função.

O teste que mais importa aqui é `test_achado_nao_tem_como_virar_evidencia`. Ele não mede um
comportamento: mede uma **impossibilidade**. O gpt-researcher aprendeu essa lição com
cicatriz — snippet longo era confundido com página baixada, e o relatório saía com citação
que não existia em lugar nenhum. Eles resolveram com uma flag; um dos provedores esqueceu
de declará-la e só não quebrou por acaso.

Aqui a diferença é de tipo: `Achado` não tem o campo que o grounding lê.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline.research import search


@pytest.fixture(autouse=True)
def cache_isolado(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Cada teste com o próprio cache de busca. Sem isso, um grava o que o outro lê."""
    monkeypatch.setattr(search, "CACHE", tmp_path / "search-cache")
    yield


class TestARegraDeEvidencia:
    def test_achado_nao_tem_como_virar_evidencia(self):
        """**A regra do produto, escrita como tipo.**

        Um `Achado` não tem `quote`, não tem `source_url` de snapshot e não tem texto de
        página. O grounding lê o texto salvo pelo `fetch`; o snippet nunca chega lá, e não
        é por disciplina — é porque não existe o campo.
        """
        achado = search.Achado(
            url="https://www.ford.com.br/ranger",
            titulo="Ranger Raptor",
            snippet="A Ranger Raptor tem 397 cv de potência",
            posicao=0,
            provedor="tavily",
            consulta="ford ranger raptor ficha",
        )
        campos = set(achado.to_dict())
        assert "quote" not in campos
        assert "texto" not in campos
        assert "evidence_quote" not in campos
        # E o snippet continua sendo o que é: metadado de roteamento.
        assert "397 cv" in achado.snippet

    def test_o_snippet_e_cortado_e_nao_guardado_inteiro(self):
        """Snippet grande engana quem lê o log: parece página. Quinhentos caracteres já são
        mais do que o suficiente para decidir se vale gastar uma das doze páginas."""
        assert search.RESULTADOS_POR_CONSULTA == 10


class TestORegistro:
    def test_os_quatro_provedores_pedidos_estao_registrados(self):
        assert {"tavily", "brave", "duckduckgo", "searxng"} <= set(search.PROVEDORES)

    def test_o_provedor_replay_existe_e_nao_toca_a_rede(self):
        """`replay` lê de `tests/fixtures/search`, e é o provedor da demonstração.

        A apresentação de 15/09 não pode depender de o buscador estar de pé, de haver
        saldo na conta, nem de a internet do auditório funcionar.
        """
        assert "replay" in search.PROVEDORES
        # Consulta sem fixture devolve lista vazia, e não exceção: com uma gravação
        # parcial, "esta consulta não rendeu" é a resposta honesta.
        assert search.PROVEDORES["replay"]().buscar("consulta que ninguém gravou") == []

    def test_replay_ainda_le_as_fixtures_gravadas_antes_da_chave_com_dominios(self):
        """As fixtures da demo usam a chave anterior; perder esse fallback zera a pesquisa."""
        consulta = "Mitsubishi Triton HPE-S 2.4 Turbodiesel AT6 4x4 ficha técnica oficial"
        achados = search.PROVEDORES["replay"]().buscar(consulta)
        assert achados, "a pesquisa replay não pode fingir que a fixture existente está vazia"
        assert any("Triton" in a.titulo for a in achados)

    def test_cada_provedor_sabe_o_proprio_nome(self):
        for nome, classe in search.PROVEDORES.items():
            assert classe.nome == nome

    def test_provedor_desconhecido_LEVANTA_em_vez_de_cair_em_outro(self):
        """O oposto do gpt-researcher, e de propósito.

        Lá, um nome inválido cai em Tavily **sem avisar**. Uma rodada em que ninguém sabe
        qual buscador respondeu é uma rodada que não se pode auditar — e o produto inteiro
        é auditoria.
        """
        with pytest.raises(search.BuscaIndisponivel, match="desconhecido"):
            search.montar("bing")

    def test_sem_provedor_configurado_tambem_levanta(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("SEARCH_PROVIDER", raising=False)
        with pytest.raises(search.BuscaIndisponivel, match="nenhum provedor"):
            search.montar("")

    def test_a_mensagem_de_erro_lista_os_conhecidos(self):
        """Erro que não diz a saída é erro que custa uma pesquisa na internet."""
        with pytest.raises(search.BuscaIndisponivel) as exc:
            search.montar("bing")
        for nome in search.PROVEDORES:
            assert nome in str(exc.value)


class TestCacheEReplay:
    def _gravar(self, consulta: str, provedor: str = "tavily") -> None:
        caminho = search.caminho_de_cache(consulta, provedor)
        caminho.parent.mkdir(parents=True, exist_ok=True)
        caminho.write_text(
            json.dumps(
                {
                    "consulta": consulta,
                    "provedor": provedor,
                    "achados": [
                        {
                            "url": "https://www.ford.com.br/picapes/ranger/",
                            "titulo": "Ranger",
                            "snippet": "ficha técnica",
                            "posicao": 0,
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    def test_replay_le_do_cache_sem_tocar_a_rede(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("REPLAY_MODE", "1")
        self._gravar("ford ranger ficha técnica oficial")
        resposta = search.buscar("ford ranger ficha técnica oficial", provedor="tavily")
        assert resposta.ok
        assert resposta.do_cache
        assert resposta.achados[0].url.startswith("https://www.ford.com.br")

    def test_replay_sem_fixture_LEVANTA_em_vez_de_ir_a_rede(self, monkeypatch: pytest.MonkeyPatch):
        """Um teste que passasse porque foi à internet não prova o que diz provar.

        E o projeto inteiro roda em replay: se a busca escapasse, o `verify-quick` passaria
        a depender de o buscador estar de pé e de haver saldo na conta.
        """
        monkeypatch.setenv("REPLAY_MODE", "1")
        with pytest.raises(search.RedeProibidaEmReplay, match="não está no cache"):
            search.buscar("consulta que ninguém gravou", provedor="tavily")

    def test_a_chave_do_cache_ignora_espaco_a_mais(self, monkeypatch: pytest.MonkeyPatch):
        """`"ford  ranger"` e `"ford ranger"` são a mesma pergunta. Duas chaves seriam duas
        buscas pagas pela mesma coisa."""
        monkeypatch.setenv("REPLAY_MODE", "1")
        self._gravar("ford ranger ficha")
        resposta = search.buscar("  ford   ranger   ficha  ", provedor="tavily")
        assert resposta.do_cache

    def test_a_chave_separa_provedores(self):
        a = search.caminho_de_cache("mesma consulta", "tavily")
        b = search.caminho_de_cache("mesma consulta", "brave")
        assert a != b

    def test_cache_corrompido_nao_derruba_a_pesquisa(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("REPLAY_MODE", "1")
        caminho = search.caminho_de_cache("consulta torta", "tavily")
        caminho.parent.mkdir(parents=True, exist_ok=True)
        caminho.write_text("{isto não é json", encoding="utf-8")
        # Cai no caminho de replay, que levanta com a mensagem certa — e não com JSONDecodeError.
        with pytest.raises(search.RedeProibidaEmReplay):
            search.buscar("consulta torta", provedor="tavily")


class TestFalhaDeProvedor:
    def test_provedor_fora_do_ar_vira_resposta_com_erro_e_nao_excecao(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """Falha de componente vira **estado explícito**, nunca "passou tudo".

        É o antipadrão que o Perplexica pratica: quando o embedding falha, ele atribui
        `similarity = 1` a todos os resultados e o filtro some sem aviso.
        """
        monkeypatch.setenv("REPLAY_MODE", "0")
        monkeypatch.setenv("SEARCH_PROVIDER", "tavily")
        monkeypatch.delenv("SEARCH_API_KEY", raising=False)
        resposta = search.buscar("qualquer coisa")
        assert not resposta.ok
        assert "SEARCH_API_KEY" in resposta.erro
        assert resposta.achados == []

    def test_resposta_com_erro_nao_tem_achado_nenhum(self):
        resposta = search.Resposta(consulta="x", provedor="tavily", erro="timeout")
        assert not resposta.ok
        assert resposta.achados == []


class TestBuscaRestritaAosDominios:
    """Procurar **onde tem ficha**, e não na web inteira.

    Medido na primeira pesquisa ao vivo da S10 (13/09/2026): dos 20 resultados da primeira
    rodada, 15 saíram como "domínio não reconhecido" — buscas pagas, páginas que nunca
    seriam coletadas. A Tavily aceita `include_domains` (até 300) e **não cobra a mais**.
    """

    def test_tavily_manda_include_domains(self, monkeypatch):
        monkeypatch.setenv("REPLAY_MODE", "0")
        vistos: list[dict] = []

        class RespostaFalsa:
            @staticmethod
            def raise_for_status() -> None:
                return None

            @staticmethod
            def json() -> dict:
                return {"results": [{"url": "https://www.icarros.com.br/x", "title": "S10"}]}

        def post_falso(url, **kwargs):
            vistos.append(kwargs.get("json") or {})
            return RespostaFalsa()

        monkeypatch.setenv("SEARCH_API_KEY", "chave-de-teste")
        import httpx

        monkeypatch.setattr(httpx, "post", post_falso)

        achados = search.Tavily().buscar("S10 ficha", dominios=("icarros.com.br", "kbb.com.br"))

        assert achados and achados[0].url.endswith("/x")
        assert vistos[0]["include_domains"] == ["icarros.com.br", "kbb.com.br"]
        assert "include_raw_content" not in vistos[0], "resumo não é evidência"

    def test_sem_dominios_a_chamada_nao_leva_o_parametro(self, monkeypatch):
        monkeypatch.setenv("REPLAY_MODE", "0")
        vistos: list[dict] = []

        class RespostaFalsa:
            @staticmethod
            def raise_for_status() -> None:
                return None

            @staticmethod
            def json() -> dict:
                return {"results": []}

        monkeypatch.setenv("SEARCH_API_KEY", "chave-de-teste")
        import httpx

        monkeypatch.setattr(
            httpx, "post", lambda url, **kw: (vistos.append(kw["json"]), RespostaFalsa())[1]
        )
        search.Tavily().buscar("S10 ficha")
        assert "include_domains" not in vistos[0]

    def test_quem_nao_tem_parametro_usa_o_operador(self):
        """Brave, DuckDuckGo e SearXNG entendem `site:` — e **um** domínio, não uma cadeia
        de `OR`, que devolve vazio com frequência nesses backends."""
        assert search.com_site("S10 ficha", ("icarros.com.br",)) == "site:icarros.com.br S10 ficha"
        assert search.com_site("S10 ficha", ()) == "S10 ficha"
        com_varios = search.com_site("S10", ("a.com.br", "b.com.br"))
        assert com_varios == "site:a.com.br S10"

    def test_a_restricao_entra_na_chave_do_cache(self, tmp_path, monkeypatch):
        """A mesma frase, restrita e aberta, são **duas** buscas. Compartilhar a chave
        faria a segunda ler do cache a resposta da primeira."""
        monkeypatch.setattr(search, "CACHE", tmp_path)
        aberta = search.caminho_de_cache("S10 ficha", "tavily")
        restrita = search.caminho_de_cache("S10 ficha", "tavily", dominios=("icarros.com.br",))
        outra = search.caminho_de_cache("S10 ficha", "tavily", dominios=("kbb.com.br",))
        assert len({aberta, restrita, outra}) == 3

    def test_a_ordem_dos_dominios_nao_muda_a_chave(self, tmp_path, monkeypatch):
        monkeypatch.setattr(search, "CACHE", tmp_path)
        um = search.caminho_de_cache("S10", "tavily", dominios=("a.com.br", "b.com.br"))
        outro = search.caminho_de_cache("S10", "tavily", dominios=("b.com.br", "a.com.br"))
        assert um == outro
