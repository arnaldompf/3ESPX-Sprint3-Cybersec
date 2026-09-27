"""O modelo sob orçamento dentro da pesquisa, e a trilha que conta o que ele fez.

Escrito em 13/09/2026, quando a Pesquisa passou a rodar com o modelo de verdade e alguém
olhando. Quatro coisas que a pesquisa anterior não fazia e estes testes fixam:

* **um documento vai ao modelo uma vez só** — a segunda rodada relia tudo e pagava de novo;
* **a cota de chamadas desliga o modelo, não a pesquisa** — a regra por regex continua
  lendo, e a trilha avisa;
* **conta sem saldo e teto de gasto param com o motivo** — a ficha sai com o que a regra
  leu, e o `fim` diz em português por quê;
* **a trilha diz quem leu o quê** (`modelo`), **quanto esperou** (`espera`) e **de onde
  veio cada número** (`campo`) — e cada evento chega ao observador **na hora**.

Nada aqui toca a rede: a busca, a coleta e o `completion` são dublados.
"""

from __future__ import annotations

import json
import time

import pytest

from pipeline import llm
from pipeline.research import gaps, run
from pipeline.research import search as busca
from pipeline.research.events import Tipo

FORD = "https://www.ford.com.br/picapes/ranger/xls/"
FORD_2 = "https://www.ford.com.br/picapes/ranger/xlt/"
FORD_3 = "https://www.ford.com.br/picapes/ranger/limited/"
FORD_4 = "https://www.ford.com.br/picapes/ranger/raptor/"
REVISTA = "https://quatrorodas.abril.com.br/noticias/ford-ranger-xls-ficha/"

#: O texto das páginas dubladas. Passa dos 200 caracteres de propósito: abaixo disso o
#: laço trata a página como "respondeu sem texto" (`MINIMO_DE_TEXTO_APROVEITAVEL`), que é
#: o caso de `TestPaginaSemTexto` e não o destes aqui.
TEXTO = (
    "Ford Ranger XLS 2026. Ficha técnica. Potência máxima: 170 cv. Torque máximo: 405 Nm. "
    "Sete airbags de série. Capacidade de carga: 1.000 kg. Tanque de combustível: 80 litros. "
    "Informações sujeitas a alteração sem aviso prévio; consulte a rede autorizada para as "
    "condições comerciais desta versão."
)
assert len(TEXTO) > 200, "as páginas dubladas precisam parecer páginas"


@pytest.fixture
def mundo_dublado(monkeypatch: pytest.MonkeyPatch, tmp_path):
    """Busca, coleta e modelo dublados; Kimi configurada sem rede; livro-razão isolado."""
    monkeypatch.setenv("LLM_FAKE", "0")
    monkeypatch.setenv("LLM_PROVIDER", "kimi")
    monkeypatch.setenv("LLM_MODEL", "kimi-k2.6")
    monkeypatch.setenv("LLM_API_KEY", "placeholder-de-teste")
    monkeypatch.setenv("LLM_MIN_INTERVAL_S", "0")
    monkeypatch.setenv("LLM_LIVRO_RAZAO", str(tmp_path / "livro.json"))
    monkeypatch.delenv("LLM_TETO_USD", raising=False)
    monkeypatch.setattr(llm, "_ultima_chamada", 0.0, raising=False)
    dormidas: list[float] = []
    monkeypatch.setattr(llm.time, "sleep", lambda s: dormidas.append(s))

    estado = {
        "urls": [FORD],
        "textos": {},
        "resposta": None,
        "erro": None,
        "dominios_pedidos": [],
    }
    vistos: list[dict] = []

    def falso(**kwargs):
        vistos.append(kwargs)
        if estado["erro"] is not None:
            raise estado["erro"]
        conteudo = estado["resposta"] or json.dumps(
            {"airbags_qtd": {"value": 7, "evidence_quote": "Sete airbags", "unit": None}}
        )
        return {
            "choices": [{"message": {"content": conteudo}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 800, "completion_tokens": 40},
        }

    monkeypatch.setattr(llm, "_completion_padrao", lambda: falso)

    def buscar_falso(consulta, *, provedor="", quantos=10, dominios=()):
        estado["dominios_pedidos"].append(tuple(dominios))
        achados = [
            busca.Achado(
                url=url,
                titulo=f"Ford Ranger — resultado {i}",
                snippet="",
                posicao=i,
                provedor="dublado",
                consulta=consulta,
            )
            for i, url in enumerate(estado["urls"])
        ]
        return busca.Resposta(consulta=consulta, provedor="dublado", achados=achados)

    monkeypatch.setattr(run.busca, "buscar", buscar_falso)

    def coletar_falso(url, **kw):
        return run.Coleta(
            texto=estado["textos"].get(url, TEXTO),
            captured_at="2026-09-13",
            sha256="f" * 64,
            http_status=200,
        )

    monkeypatch.setattr(run, "_coletar", coletar_falso)
    estado["vistos"] = vistos
    estado["dormidas"] = dormidas
    return estado


def _pesquisar(**kw):
    orcamento = kw.pop("orcamento", gaps.Orcamento(rodadas=1, paginas=6, segundos=60))
    return run.pesquisar("Ford", "Ranger", "XLS", orcamento=orcamento, **kw)


class TestUmaVezSo:
    def test_um_bloco_por_passagem_retoma_documento(self, mundo_dublado):
        """Leitura incremental e fechamento da rodada visitam blocos diferentes."""
        recheio = ("lorem ipsum dolor sit amet. " * 1500 + "\n\n") * 5
        mundo_dublado["textos"] = {FORD: recheio + TEXTO}
        resultado = _pesquisar()
        assert len(mundo_dublado["vistos"]) == 2
        assert mundo_dublado["vistos"][0]["messages"] != mundo_dublado["vistos"][1]["messages"]
        assert any("leitura pendente" in a for a in resultado.avisos)

    def test_nao_reextrai_na_segunda_rodada(self, mundo_dublado):
        """A busca devolve sempre a mesma URL. Duas rodadas, **uma** chamada."""
        resultado = _pesquisar(orcamento=gaps.Orcamento(rodadas=2, paginas=6, segundos=60))
        assert resultado.orcamento.rodadas_gastas >= 1
        assert len(mundo_dublado["vistos"]) == 1

    def test_a_segunda_rodada_coleta_de_verdade(self, mundo_dublado):
        """Rodada 2 traz uma URL nova pela consulta de lacuna: ela **é baixada e lida**.

        Até 13/09/2026 não era: o orçamento conferido antes de cada página incluía o limite
        de rodadas, e a última rodada permitida abortava a coleta antes da primeira página.
        """
        chamadas = {"n": 0}
        original = run.busca.buscar

        def por_rodada(consulta, **kw):
            chamadas["n"] += 1
            mundo_dublado["urls"] = (
                [FORD] if "ficha" in consulta or chamadas["n"] <= 3 else [FORD, FORD_2]
            )
            return original(consulta, **kw)

        run.busca.buscar = por_rodada
        resultado = _pesquisar(orcamento=gaps.Orcamento(rodadas=2, paginas=6, segundos=60))
        assert resultado.orcamento.rodadas_gastas == 2
        assert {f.url for f in resultado.fontes} >= {FORD}
        assert len(resultado.fontes) >= 1
        rodadas_com_download = {e.rodada for e in resultado.trilha.de_tipo(Tipo.BAIXADA)}
        assert 1 in rodadas_com_download

    def test_le_tier_1_antes_do_tier_3(self, mundo_dublado):
        mundo_dublado["urls"] = [REVISTA, FORD]
        resultado = _pesquisar()
        tiers = [e.dados["tier"] for e in resultado.trilha.de_tipo(Tipo.MODELO)]
        assert tiers == sorted(tiers) and tiers[0] == 1


class TestACotaDeChamadas:
    def test_gasta_a_cota_avisa_e_continua_lendo_por_regra(self, mundo_dublado):
        mundo_dublado["urls"] = [FORD, FORD_2, FORD_3, FORD_4]
        resultado = _pesquisar(
            orcamento=gaps.Orcamento(rodadas=1, paginas=6, segundos=60, chamadas_llm=2)
        )

        assert len(mundo_dublado["vistos"]) == 2
        assert resultado.orcamento.chamadas_llm_gastas == 2
        avisos = [e for e in resultado.trilha.de_tipo(Tipo.AVISO) if "cota" in e.texto]
        assert len(avisos) == 1, "o aviso da cota sai uma vez, não uma por página"
        # A pesquisa **não** para por causa da cota: os quatro documentos foram lidos.
        assert len(resultado.fontes) == 4
        assert resultado.motivo_da_parada not in {
            gaps.Motivo.MODELO_SEM_SALDO,
            gaps.Motivo.TETO_DE_GASTO,
        }
        # E a regra continuou trabalhando: potência e torque saem do fast-path.
        assert resultado.spec.motorizacao["potencia_cv"].value is not None

    def test_sem_cota_nenhuma_o_modelo_nunca_e_chamado(self, mundo_dublado):
        resultado = _pesquisar(
            orcamento=gaps.Orcamento(rodadas=1, paginas=6, segundos=60, chamadas_llm=0)
        )
        assert mundo_dublado["vistos"] == []
        assert resultado.trilha.de_tipo(Tipo.MODELO) == []


class TestOModeloIndisponivel:
    def test_sem_saldo_para_com_motivo_proprio_e_nada_e_inventado(self, mundo_dublado):
        mundo_dublado["urls"] = [FORD, FORD_2]
        mundo_dublado["erro"] = RuntimeError("429 exceeded_current_quota_error: no balance")
        resultado = _pesquisar(orcamento=gaps.Orcamento(rodadas=2, paginas=6, segundos=60))

        assert len(mundo_dublado["vistos"]) == 1, "depois da recusa por saldo, ninguém insiste"
        assert resultado.motivo_da_parada is gaps.Motivo.MODELO_SEM_SALDO
        fim = resultado.trilha.de_tipo(Tipo.FIM)[0]
        assert "saldo" in fim.texto
        # A ficha traz o que a regra leu, e só isso — cada valor com trecho.
        dados = resultado.spec.model_dump()
        for grupo in dados.values():
            if not isinstance(grupo, dict):
                continue
            for campo, celula in grupo.items():
                if isinstance(celula, dict) and celula.get("value") is not None:
                    assert celula.get("evidences"), f"{campo} sem evidência"

    def test_teto_de_gasto_para_com_motivo_proprio(self, mundo_dublado, monkeypatch, tmp_path):
        livro = tmp_path / "livro.json"
        livro.write_text(json.dumps({"desde": "2026-09-13", "usd": 5.0, "chamadas": 40}))
        monkeypatch.setenv("LLM_TETO_USD", "2")
        resultado = _pesquisar()
        assert mundo_dublado["vistos"] == []
        assert resultado.motivo_da_parada is gaps.Motivo.TETO_DE_GASTO
        fim = resultado.trilha.de_tipo(Tipo.FIM)[0]
        assert "teto" in fim.texto
        assert fim.dados["teto_usd"] == 2.0
        assert fim.dados["gasto_rodada_usd"] == 5.0


class TestATrilhaDizOQueOModeloFez:
    def test_MODELO_diz_quem_leu_o_que_e_quanto_custou(self, mundo_dublado):
        resultado = _pesquisar()
        eventos = resultado.trilha.de_tipo(Tipo.MODELO)
        assert len(eventos) == 1
        e = eventos[0]
        assert e.etiqueta == "FATO"
        assert e.dados["url"] == FORD and e.dados["tier"] == 1
        assert e.dados["tokens_entrada"] == 800 and e.dados["chamadas"] == 1
        assert "airbags_qtd" in e.dados["campos"]
        assert "ford.com.br" in e.texto and "kimi-k2.6" in e.texto

    def test_CAMPO_diz_de_onde_veio_cada_numero(self, mundo_dublado):
        resultado = _pesquisar()
        campos = resultado.trilha.de_tipo(Tipo.CAMPO)
        assert campos, "nenhum evento `campo` — a trilha não prova de onde veio o número"
        por_nome = {e.dados["campo"]: e for e in campos}
        assert "airbags_qtd" in por_nome, "o campo lido pelo modelo não apareceu"
        for e in campos:
            assert e.dados["evidence_quote"], e.texto
            assert e.dados["evidence_quote"] in TEXTO, e.texto
            assert e.dados["url"] == FORD
            assert e.etiqueta == "FATO"

    def test_ESPERA_aparece_antes_de_o_modelo_ler(self, mundo_dublado, monkeypatch):
        monkeypatch.setenv("LLM_MIN_INTERVAL_S", "21")
        monkeypatch.setattr(llm, "_ultima_chamada", time.monotonic(), raising=False)
        resultado = _pesquisar()
        esperas = resultado.trilha.de_tipo(Tipo.ESPERA)
        modelos = resultado.trilha.de_tipo(Tipo.MODELO)
        assert esperas and modelos
        assert esperas[0].ordem < modelos[0].ordem
        assert 0 < esperas[0].dados["segundos"] <= 21
        assert "aguardando" in esperas[0].texto

    def test_o_fim_traz_a_medicao_e_o_gasto(self, mundo_dublado):
        resultado = _pesquisar()
        fim = resultado.trilha.de_tipo(Tipo.FIM)[0]
        assert fim.dados["medicao"]["chamadas"] == 1
        assert fim.dados["gasto_rodada_usd"] > 0
        assert resultado.medicao is not None and resultado.medicao.chamadas == 1
        assert resultado.to_dict()["medicao"]["chamadas"] == 1


class TestOObservador:
    def test_cada_evento_chega_na_hora_e_em_ordem(self, mundo_dublado):
        recebidos = []
        resultado = _pesquisar(ao_evento=recebidos.append)
        assert [e.ordem for e in recebidos] == list(range(len(resultado.trilha.eventos)))
        assert recebidos[-1].tipo is Tipo.FIM

    def test_observador_que_levanta_nao_derruba_a_pesquisa(self, mundo_dublado):
        def explode(_evento):
            raise RuntimeError("quem assiste tropeçou")

        resultado = _pesquisar(ao_evento=explode)
        assert resultado.trilha.de_tipo(Tipo.FIM)


class TestPaginaSemTexto:
    """Medido ao vivo em 13/09/2026: duas fontes responderam com 0 e 1 caractere, e as duas
    entraram na trilha como "baixada" — inflando o contador de páginas lidas da tela."""

    def test_pagina_vazia_nao_conta_como_lida_e_diz_por_que(self, mundo_dublado):
        mundo_dublado["urls"] = [FORD, FORD_2]
        mundo_dublado["textos"] = {FORD: TEXTO, FORD_2: "  "}
        resultado = _pesquisar()

        baixadas = resultado.trilha.de_tipo(Tipo.BAIXADA)
        assert [e.dados["url"] for e in baixadas] == [FORD]
        avisos = [e for e in resultado.trilha.de_tipo(Tipo.AVISO) if "sem texto" in e.texto]
        assert len(avisos) == 1 and avisos[0].dados["url"] == FORD_2
        vazia = next(f for f in resultado.fontes if f.url == FORD_2)
        assert not vazia.baixada and vazia.erro == "página sem texto aproveitável"

    def test_a_pagina_com_texto_continua_contando(self, mundo_dublado):
        resultado = _pesquisar()
        assert len(resultado.trilha.de_tipo(Tipo.BAIXADA)) == 1


class TestODominioQueFechaAPorta:
    """Medido ao vivo em 13/09/2026, na S10 High Country: as seis páginas da rodada eram do
    mesmo domínio, as seis vieram 403, e **oito outras fontes ficaram de fora por limite de
    páginas**. Havia ficha boa na fila, atrás de seis portas fechadas."""

    #: Três endereços de imprensa (tier 3, coletável) que o classificador aceita para a
    #: Ranger — e que o dublê vai recusar com 403, como a sala de imprensa da GM fez.
    BLOQUEADAS = (
        "https://quatrorodas.abril.com.br/ranger/a",
        "https://quatrorodas.abril.com.br/ranger/b",
        "https://quatrorodas.abril.com.br/ranger/c",
    )

    def test_o_dominio_bloqueado_nao_gasta_as_outras_vagas(self, mundo_dublado, monkeypatch):
        mundo_dublado["urls"] = [*self.BLOQUEADAS, FORD]

        def coletar_falso(url, **kw):
            if "quatrorodas" in url:
                return run.Coleta(erro="bloqueada", http_status=403)
            return run.Coleta(
                texto=TEXTO, captured_at="2026-09-13", sha256="f" * 64, http_status=200
            )

        monkeypatch.setattr(run, "_coletar", coletar_falso)
        resultado = _pesquisar(orcamento=gaps.Orcamento(rodadas=1, paginas=6, segundos=60))

        tentadas = [f.url for f in resultado.fontes if "quatrorodas" in f.url]
        assert len(tentadas) == 1, f"o domínio fechado foi tentado {len(tentadas)} vezes"
        bloqueios = resultado.trilha.de_tipo(Tipo.FONTE_BLOQUEADA)
        assert len(bloqueios) == 1
        assert bloqueios[0].dados["dominio"] == "quatrorodas.abril.com.br"
        avisos = [e for e in resultado.trilha.de_tipo(Tipo.AVISO) if "fechou a porta" in e.texto]
        assert len(avisos) == 1, "o corte sai uma vez, com a conta — não uma linha por URL"
        assert avisos[0].dados["quantas"] == 2
        # E a fonte boa, que antes ficava atrás da fila, foi lida.
        assert any(f.url == FORD and f.baixada for f in resultado.fontes)

    def test_dominio_que_responde_continua_na_fila(self, mundo_dublado):
        mundo_dublado["urls"] = [FORD, FORD_2]
        resultado = _pesquisar(orcamento=gaps.Orcamento(rodadas=1, paginas=6, segundos=60))
        assert len({f.url for f in resultado.fontes if f.baixada}) == 2
        assert not [e for e in resultado.trilha.de_tipo(Tipo.AVISO) if "fechou a porta" in e.texto]

    def test_a_vaga_e_de_quem_abre_a_porta(self, mundo_dublado, monkeypatch):
        """O defeito que a primeira medição da S10 com busca restrita revelou.

        As seis primeiras da fila eram do domínio oficial (tier 1, e com razão); as duas
        primeiras vieram 403 e fecharam o domínio. Como o corte `[:cabem]` era feito
        **antes** da coleta, as fontes de ficha que a busca restrita tinha trazido nunca
        entraram: o orçamento de páginas tinha sido dado a portas fechadas.
        """
        oficiais = [f"https://www.ford.com.br/picapes/ranger/xls/{i}" for i in range(6)]
        mundo_dublado["urls"] = [*oficiais, REVISTA]

        def coletar_falso(url, **kw):
            if "ford.com.br" in url:
                return run.Coleta(erro="bloqueada", http_status=403)
            return run.Coleta(
                texto=TEXTO, captured_at="2026-09-13", sha256="f" * 64, http_status=200
            )

        monkeypatch.setattr(run, "_coletar", coletar_falso)
        resultado = _pesquisar(orcamento=gaps.Orcamento(rodadas=1, paginas=6, segundos=60))

        # Uma página gasta na porta fechada; a de ficha entrou no lugar das outras cinco.
        baixadas = [f.url for f in resultado.fontes if f.baixada]
        assert REVISTA in baixadas, "a fonte que abria ficou de fora por vaga dada a 403"
        assert sum(1 for f in resultado.fontes if "ford.com.br" in f.url) == 1
        assert resultado.cobertura.com_valor > 0


class TestAEscaladaDaColeta:
    """403 na porta da frente nao e resposta final — e a primeira das tres.

    Na S10 High Country de 13/09/2026 as seis paginas da rodada eram de chevrolet.com.br e
    as seis vieram bloqueadas. A pesquisa terminou com zero campos tendo usado so o
    `http.fetch`, enquanto o Chromium do Crawl4AI estava instalado na mesma maquina e o
    Wayback tinha a pagina arquivada. Desistir na primeira tentativa era escolha do codigo,
    nao limite do mundo.

    A ordem e sempre a mesma, e cada degrau fica na trilha: `http.fetch` -> navegador ->
    (so para tier 1) Internet Archive -> `fonte_bloqueada`. Bloqueio continua virando
    estado, nunca truque: nada aqui finge ser outro agente nem ignora robots.
    """

    def _sem_rede(self, monkeypatch, *, status="blocked", texto=""):
        from pipeline.fetch import http

        class Resposta:
            def __init__(self):
                self.status = status
                self.texto = texto
                self.conteudo = b""
                self.captured_at = "2026-09-14"
                self.sha256 = ""
                self.http_status = 403 if status == "blocked" else 200
                self.bloqueada = status == "blocked"
                self.ok = status != "blocked"
                self.motivo = ""

        monkeypatch.setattr(http, "fetch", lambda url, **kw: Resposta())
        monkeypatch.setattr(http, "modo_replay", lambda: False)

    def test_bloqueada_no_http_tenta_o_navegador(self, monkeypatch):
        from pipeline.fetch import browser

        self._sem_rede(monkeypatch)
        monkeypatch.setattr(browser, "disponivel", lambda: True)
        monkeypatch.setattr(
            browser,
            "fetch_browser",
            lambda url, **kw: browser.ResultadoNavegador(
                url=url, status="ok", markdown=TEXTO, http_status=200
            ),
        )

        coleta = run._coletar("https://www.chevrolet.com.br/picapes/s10", tier=1)
        assert coleta.texto == TEXTO
        assert coleta.via == "navegador"
        assert not coleta.erro

    def test_navegador_tambem_bloqueado_e_tier_1_vai_ao_arquivo(self, monkeypatch):
        from pipeline.fetch import browser, wayback

        self._sem_rede(monkeypatch)
        monkeypatch.setattr(browser, "disponivel", lambda: True)
        monkeypatch.setattr(
            browser,
            "fetch_browser",
            lambda url, **kw: browser.ResultadoNavegador(
                url=url, status="erro", motivo="403", http_status=403
            ),
        )
        monkeypatch.setattr(
            wayback,
            "buscar_arquivada",
            lambda url: wayback.ResultadoArquivo(
                url_original=url,
                url_arquivo=f"https://web.archive.org/web/2026/{url}",
                captured_at="2026-03-01",
                status="ok",
                texto=TEXTO,
            ),
        )

        coleta = run._coletar("https://www.chevrolet.com.br/picapes/s10", tier=1)
        assert coleta.texto == TEXTO
        assert coleta.via == "arquivo"
        assert coleta.captured_at == "2026-03-01", "a data e a da CAPTURA, nao a de hoje"

    def test_fonte_de_terceiro_bloqueada_nao_vai_ao_arquivo(self, monkeypatch):
        """O Wayback custa uma requisicao e uma espera. Para tier 3 ha outra pagina na
        fila; para a montadora, nao ha substituto."""
        from pipeline.fetch import browser, wayback

        self._sem_rede(monkeypatch)
        monkeypatch.setattr(browser, "disponivel", lambda: False)

        def nao_chamar(url):
            raise AssertionError("o arquivo nao devia ser consultado para tier 3")

        monkeypatch.setattr(wayback, "buscar_arquivada", nao_chamar)
        coleta = run._coletar("https://www.icarros.com.br/catalogo/chevrolet/s10", tier=3)
        assert coleta.erro == "bloqueada"

    def test_pagina_curta_demais_tambem_escala(self, monkeypatch):
        """`icarros.com.br/catalogo` devolveu 348 k de HTML e 3 k de texto: a ficha e
        montada por JavaScript, e o `http.fetch` so ve o esqueleto."""
        from pipeline.fetch import browser

        self._sem_rede(monkeypatch, status="ok", texto="esqueleto")
        monkeypatch.setattr(browser, "disponivel", lambda: True)
        monkeypatch.setattr(
            browser,
            "fetch_browser",
            lambda url, **kw: browser.ResultadoNavegador(
                url=url, status="ok", markdown=TEXTO, http_status=200
            ),
        )
        coleta = run._coletar("https://www.icarros.com.br/catalogo/chevrolet/s10", tier=3)
        assert coleta.texto == TEXTO
        assert coleta.via == "navegador"

    def test_site_que_exige_navegador_nao_gasta_o_http(self, monkeypatch):
        from pipeline.fetch import browser, http

        chamou_http = []
        monkeypatch.setattr(
            http, "fetch", lambda url, **kw: chamou_http.append(url) or _falhar_http()
        )
        monkeypatch.setattr(http, "modo_replay", lambda: False)
        monkeypatch.setattr(browser, "disponivel", lambda: True)
        monkeypatch.setattr(
            browser,
            "fetch_browser",
            lambda url, **kw: browser.ResultadoNavegador(
                url=url, status="ok", markdown=TEXTO, http_status=200
            ),
        )
        coleta = run._coletar("https://www.icarros.com.br/catalogo/x", tier=3, navegador=True)
        assert coleta.via == "navegador"
        assert chamou_http == []

    def test_em_replay_nada_escala(self, monkeypatch):
        """O replay resolve por snapshot em disco; navegador e arquivo iriam a rede e
        fariam o teste passar por motivo errado."""
        from pipeline.fetch import browser, http

        class Bloqueada:
            status, texto, conteudo = "blocked", "", b""
            captured_at, sha256, motivo = "", "", ""
            http_status, bloqueada, ok = 403, True, False

        monkeypatch.setattr(http, "fetch", lambda url, **kw: Bloqueada())
        monkeypatch.setattr(http, "modo_replay", lambda: True)

        def nao_chamar(*a, **kw):
            raise AssertionError("em replay o navegador nao e chamado")

        monkeypatch.setattr(browser, "disponivel", lambda: True)
        monkeypatch.setattr(browser, "fetch_browser", nao_chamar)
        assert run._coletar("https://www.chevrolet.com.br/picapes/s10", tier=1).erro == "bloqueada"


class TestOsLimitesDaEscalada:
    """Escalar custa relogio, e a copia arquivada pode ser de outro carro.

    Medido na S10 em 14/09/2026, com a escalada recem-ligada: a rodada coletou **4 paginas
    em 304 segundos** e parou por tempo, contra 12 paginas em 290 antes. A chevrolet.com.br
    esta atras de Akamai e barra tambem o Chromium, entao cada pagina do dominio pagava a
    tentativa inteira do navegador para terminar bloqueada do mesmo jeito.

    E o Internet Archive devolveu uma captura antiga da mesma URL: dela sairam, com tier 1,
    `numero_marchas 6` e `torque_nm 460` — a S10 de 2027 tem oito marchas e 510 Nm. Uma
    captura velha e uma pagina velha; a regra do ano vale para ela igual.
    """

    def test_captura_velha_demais_nao_serve(self, monkeypatch):
        from pipeline.fetch import wayback

        monkeypatch.setattr(
            wayback,
            "buscar_arquivada",
            lambda url: wayback.ResultadoArquivo(
                url_original=url,
                url_arquivo="https://web.archive.org/web/2019/" + url,
                captured_at="2019-05-02",
                status="ok",
                texto=TEXTO,
            ),
        )
        assert run._pelo_arquivo("https://www.chevrolet.com.br/picapes/s10", ano=2027) is None

    def test_captura_recente_serve(self, monkeypatch):
        from pipeline.fetch import wayback

        monkeypatch.setattr(
            wayback,
            "buscar_arquivada",
            lambda url: wayback.ResultadoArquivo(
                url_original=url,
                url_arquivo="https://web.archive.org/web/2026/" + url,
                captured_at="2026-03-01",
                status="ok",
                texto=TEXTO,
            ),
        )
        achado = run._pelo_arquivo("https://www.chevrolet.com.br/picapes/s10", ano=2027)
        assert achado is not None and achado.captured_at == "2026-03-01"

    def test_sem_ano_pedido_a_captura_passa(self, monkeypatch):
        from pipeline.fetch import wayback

        monkeypatch.setattr(
            wayback,
            "buscar_arquivada",
            lambda url: wayback.ResultadoArquivo(
                url_original=url,
                url_arquivo="a",
                captured_at="2019-05-02",
                status="ok",
                texto=TEXTO,
            ),
        )
        assert run._pelo_arquivo("https://x/y", ano=None) is not None

    def test_sem_escalar_a_coleta_para_no_primeiro_degrau(self, monkeypatch):
        """`escalar=False` e o que o laco passa quando o relogio acabou ou quando o
        dominio ja provou, nesta rodada, que nem o navegador abre."""
        from pipeline.fetch import browser, http

        class Bloqueada:
            status, texto, conteudo = "blocked", "", b""
            captured_at, sha256, motivo = "", "", ""
            http_status, bloqueada, ok = 403, True, False

        monkeypatch.setattr(http, "fetch", lambda url, **kw: Bloqueada())
        monkeypatch.setattr(http, "modo_replay", lambda: False)

        def nao_chamar(*a, **kw):
            raise AssertionError("sem escalar, o navegador nao e chamado")

        monkeypatch.setattr(browser, "disponivel", lambda: True)
        monkeypatch.setattr(browser, "fetch_browser", nao_chamar)
        coleta = run._coletar("https://www.chevrolet.com.br/picapes/s10", tier=1, escalar=False)
        assert coleta.erro == "bloqueada"


def _falhar_http():
    raise AssertionError("o http nao devia ser chamado")
