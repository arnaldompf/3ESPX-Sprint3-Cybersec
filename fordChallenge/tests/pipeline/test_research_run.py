"""O motor do Pesquisador, ponta a ponta, em replay.

**O teste que mais importa deste arquivo é `test_com_o_LLM_quebrado_nada_e_inventado`.**
Ele roda a pesquisa inteira com o provedor de linguagem levantando exceção em toda chamada,
e exige que a ficha saia **vazia ou só com o que o fast-path leu** — nunca com um número
que ninguém viu numa página.

É a lição do Simplicity: quando a busca vivia dentro de um laço de *tool-calls*, provedores
sem suporte a tool-call devolviam zero fontes **em silêncio** e o modelo respondia de
cabeça. Eles resolveram movendo a decisão para o código, e escreveram o teste com o LLM
quebrado. Nós fazemos o mesmo, e por isso a regra é garantia e não pedido.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline.research import gaps, planner, run
from pipeline.research import search as busca
from pipeline.research.events import Tipo, Trilha

FIXTURES = Path("tests/fixtures/search")
SNAPSHOTS = Path("tests/fixtures/snapshots")


@pytest.fixture(autouse=True)
def busca_gravada(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Cache de busca isolado por teste, semeado com as fixtures gravadas."""
    cache = tmp_path / "search-cache"
    monkeypatch.setattr(busca, "CACHE", cache)
    monkeypatch.setenv("REPLAY_MODE", "1")
    monkeypatch.setenv("LLM_FAKE", "1")
    monkeypatch.setenv("SEARCH_PROVIDER", "tavily")
    yield cache


def semear(cache: Path, consulta: str, urls: list[str], provedor: str = "tavily") -> None:
    """Grava uma resposta de busca como se o provedor a tivesse devolvido."""
    caminho = busca.caminho_de_cache(consulta, provedor)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(
        json.dumps(
            {
                "consulta": consulta,
                "provedor": provedor,
                "achados": [
                    {
                        "url": url,
                        "titulo": f"resultado {i}",
                        # O snippet traz o número certo **de propósito**: é o que prova que
                        # ele não vira evidência. Se um destes valores aparecer na ficha
                        # sem a página ter sido baixada, a regra foi furada.
                        "snippet": "A Ranger Raptor tem 397 cv e 583 Nm de torque",
                        "posicao": i,
                    }
                    for i, url in enumerate(urls)
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def semear_o_plano(cache: Path, urls: list[str], marca="Ford", modelo="Ranger", versao="") -> None:
    """Semeia **todas** as consultas do plano com as mesmas URLs.

    Em replay, uma consulta sem fixture levanta — e é isso que se quer no teste de
    disciplina. Aqui o alvo é outro, então o plano inteiro é semeado.
    """
    from pipeline.research import planner

    alvo = planner.Alvo(marca, modelo, versao)
    for consulta in planner.primeira_rodada(alvo):
        semear(cache, consulta.texto, urls)


def fonte_da_fixture(version_id: str, source_id: str) -> run.Fonte:
    pastas = list((SNAPSHOTS / version_id).glob(f"*/{source_id}"))
    assert len(pastas) == 1
    pasta = pastas[0]
    meta = json.loads((pasta / "meta.json").read_text(encoding="utf-8"))
    return run.Fonte(
        url=meta["url_final"],
        tier=meta["tier"],
        tipo=meta["tipo"],
        motivo="fixture gravada",
        consulta="teste do conector dentro da pesquisa",
        texto=(pasta / meta["text_path"]).read_text(encoding="utf-8"),
        captured_at=meta["captured_at"],
        baixada=True,
    )


class TestConectoresDentroDaPesquisa:
    def leitor(self, marca: str, modelo: str, versao: str, ano: int) -> run.Leitor:
        alvo = planner.Alvo(marca, modelo, versao, ano)
        return run.Leitor(alvo, gaps.Orcamento(chamadas_llm=0), Trilha())

    def test_fipe_baixada_pela_pesquisa_vira_preco_com_referencia(self):
        fonte = fonte_da_fixture("chevrolet_s10_high_country_2027", "fipe_s10_high_country")
        leitor = self.leitor("Chevrolet", "S10", "High Country", 2027)

        spec, _ = leitor.ler(
            run._documentos_de([fonte]),
            campos=["preco_fipe_brl", "fipe_referencia"],
            fontes=[fonte],
        )

        assert spec.comercial["preco_fipe_brl"].value == 294_378
        assert spec.comercial["fipe_referencia"].value == "2026-09"
        assert spec.comercial["preco_fipe_brl"].evidences[0].quote in fonte.texto

    def test_tabela_pbe_sem_ano_modelo_na_linha_fica_pendente(self):
        fonte = fonte_da_fixture("ford_ranger_limited_2027", "pbe_tabela")
        leitor = self.leitor("Ford", "Ranger", "Limited 3.0 V6", 2027)

        spec, _ = leitor.ler(
            run._documentos_de([fonte]),
            campos=["consumo_urbano_kml", "consumo_rodoviario_kml"],
            fontes=[fonte],
        )

        assert spec.desempenho["consumo_urbano_kml"].value is None
        assert spec.desempenho["consumo_rodoviario_kml"].value is None

    def test_fipe_de_outra_versao_nao_e_fundida(self):
        fonte = fonte_da_fixture("ford_ranger_limited_2027", "fipe_ranger_limited")
        leitor = self.leitor("Ford", "Ranger", "Raptor 3.0 V6", 2027)

        spec, avisos = leitor.ler(
            run._documentos_de([fonte]),
            campos=["preco_fipe_brl", "fipe_referencia"],
            fontes=[fonte],
        )

        assert spec.comercial["preco_fipe_brl"].value is None
        assert any("outra versao" in aviso.lower() for aviso in avisos)

    def test_pagina_com_varias_versoes_nao_contamina_a_versao_pedida(self):
        texto = """Brasil. Linha 2026. Motor 2.4 Turbodiesel AT6 4x4.
Mitsubishi L200 Triton Sport Outdoor GLS 2.4 AT: rodas aro 18
Mitsubishi L200 Triton Sport HPE-S 2.4 AT: farois de LED
Mitsubishi L200 Triton Sport Terra 2.4 AT: rodas aro 20"""
        fonte = run.Fonte(
            url="https://revista.test/triton",
            tier=3,
            tipo="imprensa",
            motivo="teste",
            consulta="teste",
            texto=texto,
            captured_at="2026-09-14",
            baixada=True,
        )
        leitor = self.leitor("Mitsubishi", "Triton", "HPE-S 2.4 Turbodiesel AT6 4x4", 2026)

        spec, avisos = leitor.ler(
            run._documentos_de([fonte]),
            campos=["rodas_aro_pol", "farois_tipo"],
            fontes=[fonte],
        )

        assert spec.exterior["rodas_aro_pol"].value is None
        assert spec.exterior["farois_tipo"].value == "LED"
        assert any("no de" in aviso for aviso in avisos)


class TestOLacoEAGarantia:
    def test_com_o_LLM_quebrado_nada_e_inventado(
        self, busca_gravada: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """**A prova de que a regra é arquitetura, e não um pedido no prompt.**

        Com o provedor de linguagem levantando em toda chamada, a pesquisa termina e a
        ficha não tem um único valor sem trecho verbatim. O que sobra é o que o fast-path
        leu por regex do texto salvo — que é exatamente o que deve sobrar.
        """
        from pipeline import llm

        def explode(*_args, **_kwargs):
            raise RuntimeError("provedor de linguagem fora do ar")

        monkeypatch.setattr(llm, "completar", explode, raising=False)
        monkeypatch.setattr(llm, "extrair", explode, raising=False)

        semear_o_plano(
            busca_gravada,
            ["https://www.ford.com.br/picapes/ranger-raptor/"],
            versao="Raptor 3.0 V6 Bi-turbo 4WD AT",
        )
        resultado = run.pesquisar(
            "Ford",
            "Ranger",
            "Raptor 3.0 V6 Bi-turbo 4WD AT",
            orcamento=gaps.Orcamento(rodadas=1, paginas=3, segundos=60),
        )

        dados = resultado.spec.model_dump()
        for grupo in dados.values():
            if not isinstance(grupo, dict):
                continue
            for campo, celula in grupo.items():
                if not isinstance(celula, dict) or celula.get("value") is None:
                    continue
                evidencias = celula.get("evidences") or []
                assert evidencias, f"{campo} saiu com valor e sem evidência"
                for evidencia in evidencias:
                    assert evidencia.get("quote"), f"{campo}: evidência sem trecho"

    def test_o_snippet_nunca_vira_evidencia(self, busca_gravada: Path):
        """O snippet semeado diz "397 cv". Se a página não baixar, o campo fica vazio.

        É a cicatriz do gpt-researcher virando teste: lá, snippet longo era confundido com
        página baixada, e o relatório saía com citação que não existia em lugar nenhum.
        """
        semear_o_plano(
            busca_gravada, ["https://www.ford.com.br/nao-existe-esta-pagina"], versao="Raptor"
        )
        resultado = run.pesquisar(
            "Ford",
            "Ranger",
            "Raptor",
            orcamento=gaps.Orcamento(rodadas=1, paginas=2, segundos=30),
        )
        potencia = resultado.spec.motorizacao.get("potencia_cv")
        assert potencia is None or potencia.value is None, (
            "o número do snippet chegou à ficha sem a página ter sido lida"
        )

    def test_sem_fixture_de_busca_o_run_nao_vai_a_rede_e_diz_por_que(self, busca_gravada: Path):
        """Em replay, **nada** sai para a rede — nem a busca.

        Sem nenhuma fixture, a pesquisa termina sem fonte e **explica**: cada consulta
        vira um aviso nomeando a consulta que faltou. Deixar a exceção subir pareceria mais
        rigoroso e seria pior — uma gravação com nove das dez consultas mataria o run
        inteiro, e quem estivesse gravando a décima não saberia por quê.
        """
        resultado = run.pesquisar(
            "Ford",
            "Ranger",
            "Raptor",
            orcamento=gaps.Orcamento(rodadas=1, paginas=2, segundos=30),
        )
        assert resultado.fontes == []
        assert any("sem fixture de busca" in a for a in resultado.avisos)
        assert resultado.cobertura.com_valor == 0


class TestOOrcamento:
    def test_para_no_limite_de_rodadas_e_DIZ_qual_foi(self, busca_gravada: Path):
        """ "Acabou" não é resposta. Com três minutos de orçamento, saber se a pesquisa
        parou por ter fechado tudo, por ter gastado as páginas ou por ter estourado o
        relógio é a diferença entre "a fonte não tem" e "não deu tempo"."""
        semear_o_plano(
            busca_gravada, ["https://www.ford.com.br/picapes/ranger-raptor/"], versao="Raptor"
        )
        resultado = run.pesquisar(
            "Ford",
            "Ranger",
            "Raptor",
            orcamento=gaps.Orcamento(rodadas=1, paginas=20, segundos=120),
        )
        assert resultado.motivo_da_parada in set(gaps.Motivo)
        assert resultado.orcamento.rodadas_gastas <= 1
        fim = resultado.trilha.de_tipo(Tipo.FIM)
        assert fim and len(fim[0].texto) > 20

    def test_para_no_limite_de_paginas(self, busca_gravada: Path):
        semear_o_plano(
            busca_gravada,
            [
                "https://www.ford.com.br/picapes/ranger-raptor/",
                "https://www.ford.com.br/picapes/ranger/",
                "https://quatrorodas.abril.com.br/ranger",
            ],
            versao="Raptor",
        )
        resultado = run.pesquisar(
            "Ford",
            "Ranger",
            "Raptor",
            orcamento=gaps.Orcamento(rodadas=5, paginas=2, segundos=120),
        )
        assert resultado.orcamento.paginas_gastas <= 2

    def test_o_relogio_e_conferido_ANTES_de_cada_pagina(self):
        """O defeito que a primeira rodada ao vivo revelou, em 13/09/2026.

        Com teto de 170 s, o primeiro veículo passou de **3,2 minutos**: o orçamento só era
        conferido entre rodadas, e uma página lenta pendura a coleta sem que ninguém olhe o
        relógio. Numa demonstração, "três minutos" tem de ser três minutos — e um limite
        conferido só no fim é um limite que já foi estourado quando alguém pergunta.
        """
        import time

        orcamento = gaps.Orcamento(rodadas=5, paginas=20, segundos=60)
        # Relógio adiantado em uma hora: o próximo `estourou()` tem de acusar.
        orcamento._inicio = time.monotonic() - 3600
        assert orcamento.estourou() is gaps.Motivo.TEMPO

    def test_o_orcamento_padrao_e_o_da_demonstracao(self):
        padrao = gaps.Orcamento()
        assert (padrao.rodadas, padrao.paginas, padrao.segundos) == (2, 12, 180.0)


class TestATrilha:
    def test_a_consulta_aparece_verbatim_na_trilha(self, busca_gravada: Path):
        """Não uma paráfrase: a consulta exata. É o que permite a alguém repetir a busca."""
        semear_o_plano(
            busca_gravada, ["https://www.ford.com.br/picapes/ranger-raptor/"], versao="Raptor"
        )
        resultado = run.pesquisar(
            "Ford",
            "Ranger",
            "Raptor",
            orcamento=gaps.Orcamento(rodadas=1, paginas=2, segundos=60),
        )
        consultas = resultado.trilha.consultas
        assert consultas
        assert any("ficha técnica" in c for c in consultas)

    def test_a_fonte_descartada_aparece_com_o_motivo(self, busca_gravada: Path):
        """Descarte silencioso é indistinguível de fonte que ninguém viu."""
        semear_o_plano(
            busca_gravada,
            [
                "https://www.ford.com.br/picapes/ranger-raptor/",
                "https://www.youtube.com/watch?v=abc",
                "https://blogdocarro.net/ranger",
            ],
            versao="Raptor",
        )
        resultado = run.pesquisar(
            "Ford",
            "Ranger",
            "Raptor",
            orcamento=gaps.Orcamento(rodadas=1, paginas=3, segundos=60),
        )
        descartadas = resultado.trilha.de_tipo(Tipo.FONTE_DESCARTADA)
        assert descartadas, "nenhuma fonte descartada apareceu na trilha"
        for evento in descartadas:
            assert evento.dados.get("motivo")

    def test_todo_evento_tem_etiqueta(self, busca_gravada: Path):
        """`docs/13` §2: nenhuma informação na tela sem etiqueta — inclusive aqui."""
        semear_o_plano(
            busca_gravada, ["https://www.ford.com.br/picapes/ranger-raptor/"], versao="Raptor"
        )
        resultado = run.pesquisar(
            "Ford",
            "Ranger",
            "Raptor",
            orcamento=gaps.Orcamento(rodadas=1, paginas=2, segundos=60),
        )
        for evento in resultado.trilha.eventos:
            assert evento.etiqueta in {"FATO", "INFERENCIA", "SIMULACAO"}

    def test_a_trilha_sai_em_SSE_valido(self, busca_gravada: Path):
        semear_o_plano(
            busca_gravada, ["https://www.ford.com.br/picapes/ranger-raptor/"], versao="Raptor"
        )
        resultado = run.pesquisar(
            "Ford",
            "Ranger",
            "Raptor",
            orcamento=gaps.Orcamento(rodadas=1, paginas=2, segundos=60),
        )
        for evento in resultado.trilha.eventos:
            linhas = evento.sse().split("\n")
            assert linhas[0].startswith("event: ")
            assert linhas[1].startswith("data: ")
            json.loads(linhas[1][len("data: ") :])  # tem de ser JSON de uma linha só


class TestTextoDaPaginaRedecodificaCharset:
    """O `carrosnaweb` é windows-1252 e não declara isso no cabeçalho HTTP — sem
    corrigir, o `httpx`/upstream decodifica como utf-8 com substituição, o acento vira
    "�" e o `evidence_quote` verbatim deixa de casar no texto salvo (grounding falha em
    silêncio). `_texto_da_pagina` recebe os bytes originais e corrige a partir deles.
    """

    def test_html_mal_decodificado_e_recuperado_a_partir_dos_bytes(self):
        conteudo = (
            b'<html><head><meta http-equiv="Content-Type" '
            b'content="text/html; charset=windows-1252"></head>'
            b"<body><p>Suspens\xe3o dianteira</p></body></html>"
        )
        texto_mojibake = conteudo.decode("utf-8", errors="replace")
        assert "�" in texto_mojibake

        resultado = run._texto_da_pagina(
            "https://www.carrosnaweb.com.br/fichadetalhe.asp?codigo=1",
            texto_mojibake,
            conteudo,
        )
        assert isinstance(resultado, str)
        assert "Suspensão dianteira" in resultado
        assert "�" not in resultado

    def test_html_ja_correto_nao_e_tocado(self):
        conteudo = "<html><body><p>Suspensão dianteira</p></body></html>".encode()
        resultado = run._texto_da_pagina(
            "https://www.example.test/pagina", conteudo.decode("utf-8"), conteudo
        )
        assert "Suspensão dianteira" in resultado
