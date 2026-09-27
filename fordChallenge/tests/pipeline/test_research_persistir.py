"""A ficha pesquisada entra no catálogo — e entra do jeito que o resto do sistema lê.

Item A do `specs/BACKLOG.md` até 13/09/2026: a pesquisa terminava, a trilha ficava, e a
ficha evaporava. O que estes testes fixam é o contrário, com as regras do resto do pipeline:
versão só com nome e ano, evidência ligada ao snapshot, re-pesquisa que substitui sem apagar
uma ficha boa por nada, e o carro passando a existir para `spec_assembler` e para o
Benchmark.

Banco SQLite descartável por teste; `REPLAY_MODE=1` (o `conftest` garante). O fixture
fornece cópias locais com hash real para revalidar as evidências, sem executar coleta.
O teste da escrita de snapshots desliga o replay de propósito.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from pipeline import llm
from pipeline.research import gaps, run
from pipeline.research.events import Trilha
from pipeline.research.persistir import persistir_pesquisa
from pipeline.schema import Evidence, SpecField, Status, empty_spec

URL = "https://www.mitsubishimotors.com.br/veiculos/triton/hpe-s"
URL_PDF = "https://www.mitsubishimotors.com.br/docs/triton-2026.pdf"
BLOQUEADA = "https://www.mitsubishimotors.com.br/imprensa/"
TEXTO = "Mitsubishi Triton HPE-S 2026. Potência máxima: 205 cv. Torque: 470 Nm. Sete airbags."
TEXTO_NOVO = "Mitsubishi Triton HPE-S 2026. Potência máxima: 210 cv. Tanque: 80 litros."
TEXTO_TANQUE = "Mitsubishi Triton HPE-S 2026. Tanque: 80 litros."
TEXTO_REVISTA = "Mitsubishi Triton HPE-S 2026. Potência declarada: 210 cv. Medida: 215 cv."


@pytest.fixture
def sessao(tmp_path: Path, monkeypatch):
    import api.app.models  # noqa: F401  (registra as tabelas)
    import pipeline.research.persistir as persist_module
    from pipeline.fetch import http

    original = persist_module._snapshot_em_disco
    fixture_dir = tmp_path / "sources"
    fixture_dir.mkdir()

    def fixture_snapshot(fonte, version_id):
        if not http.modo_replay():
            return original(fonte, version_id)
        digest = hashlib.sha256(fonte.texto.encode()).hexdigest()
        path = fixture_dir / f"{digest[:16]}.txt"
        path.write_text(fonte.texto, encoding="utf-8", newline="\n")
        return str(path), digest

    monkeypatch.setattr(persist_module, "_snapshot_em_disco", fixture_snapshot)

    motor = create_engine(f"sqlite:///{(tmp_path / 'catalogo.db').as_posix()}")
    SQLModel.metadata.create_all(motor)
    with Session(motor) as s:
        yield s


def _evidencia(quote: str = "205 cv", url: str = URL, tier: int = 1) -> Evidence:
    return Evidence(
        evidence_id="e1", source_url=url, tier=tier, quote=quote, captured_at="2026-09-13"
    )


def _spec(**campos):
    """Uma ficha com os campos pedidos verificados; `{}` para ficha vazia."""
    spec = empty_spec(job_id="research:teste")
    for caminho, (valor, unit, quote) in campos.items():
        spec.set(
            caminho,
            SpecField.verificado(valor, _evidencia(quote), unit=unit),
        )
    return spec


def _resultado(spec, *, fontes=None, medicao=None, texto=TEXTO):
    return run.Resultado(
        marca="Mitsubishi",
        modelo="Triton",
        versao="HPE-S",
        spec=spec,
        trilha=Trilha(),
        cobertura=gaps.medir(spec),
        orcamento=gaps.Orcamento(),
        motivo_da_parada=gaps.Motivo.COBERTURA,
        fontes=fontes
        if fontes is not None
        else [
            run.Fonte(
                url=URL,
                tier=1,
                motivo="domínio oficial",
                consulta="q",
                texto=texto,
                captured_at="2026-09-13" if texto == TEXTO else "2026-09-14",
                baixada=True,
                sha256=hashlib.sha256(texto.encode()).hexdigest(),
                http_status=200,
            )
        ],
        medicao=medicao,
    )


FICHA = {
    "motorizacao.potencia_cv": (205, "cv", "205 cv"),
    "motorizacao.torque_nm": (470, "Nm", "470 Nm"),
}


def _job_de_pesquisa(sessao) -> str:
    """Um `Job(tipo="research")`, para a gravação saber que a linha veio de pesquisa.

    É o que separa "a montadora disse" de "uma pesquisa achou": o caminho
    `SpecValue.extraction_id → Extraction.job_id → Job.tipo`. Sem job, a linha conta como
    coleta dirigida — que é o que o `seed` do gabarito produz.
    """
    from api.app.models import Job, JobStatus

    job = Job(tipo="research", status=JobStatus.CONCLUIDO.value, payload={})
    sessao.add(job)
    sessao.flush()
    return job.id


def _gravar(sessao, resultado, **kw):
    base = {
        "run_id": "run-1",
        "marca": "Mitsubishi",
        "modelo": "Triton",
        "versao": "HPE-S",
        "ano_modelo": 2026,
    }
    base.update(kw)
    saida = persistir_pesquisa(sessao, resultado, **base)
    sessao.commit()
    return saida


class TestOCatalogo:
    def test_cria_marca_modelo_e_versao_em_linha(self, sessao):
        from api.app.models import Brand, VehicleModel, Version

        saida = _gravar(sessao, _resultado(_spec(**FICHA)))

        assert saida.ok, saida.erros
        assert saida.criou_versao and saida.version_id
        versao = sessao.get(Version, saida.version_id)
        assert versao is not None
        assert versao.nome_exato == "HPE-S" and versao.ano_modelo == 2026
        assert versao.in_lineup is True and versao.lineup_checked_at is not None
        modelo = sessao.get(VehicleModel, versao.model_id)
        assert modelo.nome == "Triton"
        assert sessao.get(Brand, modelo.brand_id).nome == "Mitsubishi"

    def test_e_idempotente_na_versao(self, sessao):
        primeira = _gravar(sessao, _resultado(_spec(**FICHA)))
        segunda = _gravar(sessao, _resultado(_spec(**FICHA)))
        assert primeira.version_id == segunda.version_id
        assert segunda.criou_versao is False

    def test_o_nome_da_versao_e_canonico(self, sessao):
        """ "Triton HPE-S" vira "HPE-S": o catálogo não repete o modelo dentro da versão."""
        from api.app.models import Version

        saida = _gravar(sessao, _resultado(_spec(**FICHA)), versao="Triton HPE-S")
        assert sessao.get(Version, saida.version_id).nome_exato == "HPE-S"

    @pytest.mark.parametrize("faltando", ["versao", "ano_modelo"])
    def test_sem_versao_ou_sem_ano_nao_cria_e_explica(self, sessao, faltando):
        from api.app.models import Version

        saida = _gravar(
            sessao,
            _resultado(_spec(**FICHA)),
            **{faltando: None if faltando == "ano_modelo" else ""},
        )
        assert saida.version_id is None
        assert saida.erros and ("versão" in saida.erros[0] or "ano-modelo" in saida.erros[0])
        assert sessao.exec(select(Version)).all() == []


class TestAFicha:
    def test_valores_evidencias_e_snapshot_ligados(self, sessao):
        from api.app.models import Evidence as EvidenceRow
        from api.app.models import Snapshot, Source, SpecValue

        saida = _gravar(sessao, _resultado(_spec(**FICHA)))

        assert saida.snapshots == 1 and saida.evidences == 2
        snap = sessao.exec(select(Snapshot)).one()
        assert snap.url == URL and snap.sha256 == hashlib.sha256(TEXTO.encode()).hexdigest()
        assert snap.http_status == 200
        assert snap.version_id == saida.version_id
        assert snap.text_path and Path(snap.text_path).read_text(encoding="utf-8") == TEXTO
        assert sessao.exec(select(Source)).one().tier == 1

        com_valor = [
            v
            for v in sessao.exec(select(SpecValue).where(SpecValue.version_id == saida.version_id))
            if v.value_json is not None
        ]
        assert {v.field for v in com_valor} == {"potencia_cv", "torque_nm"}
        for v in com_valor:
            ev = sessao.get(EvidenceRow, v.evidence_id)
            assert ev is not None and ev.quote in {"205 cv", "470 Nm"}
            assert ev.snapshot_id == snap.id, "a evidência tem de apontar para o snapshot"
            assert ev.captured_at == snap.captured_at

    def test_so_fonte_baixada_vira_snapshot(self, sessao):
        from api.app.models import Snapshot

        fontes = [
            run.Fonte(url=URL, tier=1, motivo="oficial", consulta="q", texto=TEXTO, baixada=True),
            run.Fonte(
                url=URL_PDF,
                tier=1,
                motivo="pdf",
                consulta="q",
                texto="",
                baixada=False,
                erro="timeout",
            ),
        ]
        saida = _gravar(sessao, _resultado(_spec(**FICHA), fontes=fontes))
        assert saida.snapshots == 1
        assert [s.url for s in sessao.exec(select(Snapshot))] == [URL]

    def test_o_custo_da_leitura_fica_registrado(self, sessao):
        from api.app.models import Extraction

        medicao = llm.Medicao()
        medicao.somar(llm.Uso("kimi-k2.6", tokens_entrada=800, tokens_saida=40, provedor="kimi"))
        _gravar(sessao, _resultado(_spec(**FICHA), medicao=medicao))
        extracao = sessao.exec(select(Extraction)).one()
        assert extracao.tokens_entrada == 800 and extracao.tokens_saida == 40
        assert extracao.custo_usd > 0

    def test_a_ficha_montada_pela_api_mostra_o_valor_com_a_evidencia(self, sessao):
        from api.app.services import spec_assembler

        saida = _gravar(sessao, _resultado(_spec(**FICHA)))
        ficha = spec_assembler.montar(sessao, saida.version_id)
        potencia = ficha.motorizacao["potencia_cv"]
        assert potencia.value == 205 and potencia.status is Status.VERIFICADO
        assert potencia.evidences and potencia.evidences[0].quote == "205 cv"

    def test_o_benchmark_passa_a_enxergar_a_versao(self, sessao):
        from api.app.routers.benchmark import _versoes_do_modelo

        saida = _gravar(sessao, _resultado(_spec(**FICHA)))
        assert [v.id for v in _versoes_do_modelo(sessao, "Mitsubishi", "Triton", 2026)] == [
            saida.version_id
        ]
        assert _versoes_do_modelo(sessao, "Mitsubishi", "Triton", 2025) == []


class TestAFusao:
    """**Completar, não substituir** — a regra que a S10 High Country ensinou.

    Medido ao vivo em 13/09/2026: a pesquisa voltou com 32 campos e **apagou os 12 campos
    tier 1** que o gabarito tinha da `chevrolet.com.br`. Três ficaram vazios (a pesquisa
    não os achou) e `deslocamento_l` virou **zero**. A ficha ficou pior depois de pesquisar.

    A regra de substituir estava certa para uma ficha inteira de pesquisa, e errada para
    qualquer versão que já tivesse algo melhor.
    """

    def test_o_que_veio_da_coleta_dirigida_fica(self, sessao):
        from api.app.models import SpecValue

        # O gabarito: potência 205 cv, sem job de pesquisa (é o que o `seed` produz).
        primeira = _gravar(sessao, _resultado(_spec(**FICHA)))

        # A pesquisa acha 210 cv na revista, e um campo que o gabarito não tinha.
        nova = {
            "motorizacao.potencia_cv": (210, "cv", "210 cv"),
            "dimensoes.tanque_l": (80, "l", "80 litros"),
        }
        segunda = _gravar(
            sessao, _resultado(_spec(**nova), texto=TEXTO_NOVO), job_id=_job_de_pesquisa(sessao)
        )

        assert segunda.version_id == primeira.version_id
        potencias = sessao.exec(
            select(SpecValue).where(
                SpecValue.version_id == primeira.version_id, SpecValue.field == "potencia_cv"
            )
        ).all()
        valores = {p.value_json for p in potencias}
        assert valores == {205, 210}, "o valor do gabarito foi apagado"
        assert segunda.fusao.divergencias == 1
        # E o campo que faltava entrou.
        tanque = sessao.exec(
            select(SpecValue).where(
                SpecValue.version_id == primeira.version_id,
                SpecValue.field == "tanque_l",
                SpecValue.value_json.is_not(None),
            )
        ).one()
        assert tanque.value_json == 80
        assert segunda.fusao.preenchidos >= 1

    def test_a_divergencia_aparece_na_ficha_montada(self, sessao):
        from api.app.services import spec_assembler

        saida = _gravar(sessao, _resultado(_spec(**FICHA)))
        _gravar(
            sessao,
            _resultado(
                _spec(**{"motorizacao.potencia_cv": (210, "cv", "210 cv")}), texto=TEXTO_NOVO
            ),
            job_id=_job_de_pesquisa(sessao),
        )
        ficha = spec_assembler.montar(sessao, saida.version_id)
        potencia = ficha.motorizacao["potencia_cv"]
        assert potencia.status is Status.DIVERGENTE
        assert {potencia.value, *(c.value for c in potencia.conflicts)} == {205, 210}

    def test_o_mesmo_valor_nao_vira_linha_nova(self, sessao):
        """Sem isto, cada rodada gravaria o mesmo número de novo e a ficha mostraria
        "divergente" contra ela mesma."""
        from api.app.models import SpecValue

        primeira = _gravar(sessao, _resultado(_spec(**FICHA)))
        segunda = _gravar(sessao, _resultado(_spec(**FICHA)), job_id=_job_de_pesquisa(sessao))

        potencias = sessao.exec(
            select(SpecValue).where(
                SpecValue.version_id == primeira.version_id, SpecValue.field == "potencia_cv"
            )
        ).all()
        assert len(potencias) == 1
        assert segunda.fusao.iguais >= 1 and segunda.fusao.divergencias == 0

    def test_a_linha_de_pesquisa_anterior_e_que_sai(self, sessao):
        """Duas pesquisas seguidas não empilham: a segunda viu as mesmas fontes, ou
        melhores."""
        from api.app.models import SpecValue

        job = _job_de_pesquisa(sessao)
        primeira = _gravar(sessao, _resultado(_spec(**FICHA)), job_id=job)
        segunda = _gravar(
            sessao,
            _resultado(
                _spec(**{"motorizacao.potencia_cv": (210, "cv", "210 cv")}), texto=TEXTO_NOVO
            ),
            job_id=_job_de_pesquisa(sessao),
        )

        potencias = sessao.exec(
            select(SpecValue).where(
                SpecValue.version_id == primeira.version_id,
                SpecValue.field == "potencia_cv",
                SpecValue.value_json.is_not(None),
            )
        ).all()
        assert {p.value_json for p in potencias} == {205, 210}
        assert segunda.fusao.divergencias == 1
        assert segunda.fusao.substituidos == 0

    def test_valor_vazio_nao_apaga_valor_cheio(self, sessao):
        """Foi o que aconteceu com `adas_itens` e o preço da S10: a pesquisa não achou, e
        o que o gabarito tinha sumiu."""
        from api.app.models import SpecValue

        primeira = _gravar(sessao, _resultado(_spec(**FICHA)))
        _gravar(
            sessao,
            _resultado(_spec(**{"dimensoes.tanque_l": (80, "l", "80 litros")}), texto=TEXTO_TANQUE),
            job_id=_job_de_pesquisa(sessao),
        )
        potencia = sessao.exec(
            select(SpecValue).where(
                SpecValue.version_id == primeira.version_id,
                SpecValue.field == "potencia_cv",
                SpecValue.value_json.is_not(None),
            )
        ).one()
        assert potencia.value_json == 205

    def test_campo_divergente_na_propria_pesquisa_conta_uma_vez(self, sessao):
        """Uma pesquisa pode voltar **dividida contra si mesma**: duas fontes, dois valores.

        `_valores_a_gravar` então rende **duas linhas do mesmo campo**, e a fusão precisa
        decidir uma vez por campo, não uma vez por linha. Medido em 14/09/2026 na S10: o
        laço por linha apagava a linha do gabarito na primeira passagem e tentava apagá-la
        de novo na segunda (`SAWarning: DELETE ... 0 were matched`), e contava a mesma
        divergência duas vezes — a conversa dizia "16 divergências" onde havia 7 campos.
        """
        from pipeline.schema import Conflict

        _gravar(sessao, _resultado(_spec(**FICHA)))

        spec = empty_spec(job_id="research:teste")
        spec.set(
            "motorizacao.potencia_cv",
            SpecField(
                value=210,
                unit="cv",
                status=Status.DIVERGENTE,
                confidence=0.6,
                evidences=[_evidencia("210 cv", tier=3)],
                conflicts=[
                    Conflict(value=215, evidence=_evidencia("215 cv", tier=3)),
                ],
            ),
        )
        segunda = _gravar(
            sessao, _resultado(spec, texto=TEXTO_REVISTA), job_id=_job_de_pesquisa(sessao)
        )

        assert segunda.fusao.divergencias == 0, "fontes inferiores não derrubam a decisão oficial"
        assert segunda.fusao.mantidos == len(FICHA), (
            "cada valor do gabarito contado uma vez — o da divergência e o que a pesquisa nem tocou"
        )
        assert segunda.fusao.linhas == 1, "somente a decisão principal é projetada"
        assert segunda.fusao.removidas == 1, "a projeção muda; histórico e evidência ficam"
        assert segunda.fusao.erros == []

    def test_mantidos_conta_valor_preservado_e_nao_campo_vazio(self, sessao):
        """`mantidos` é o número que a conversa mostra — "manteve N do gabarito".

        Uma ficha tem 55 campos e quase todos voltam vazios de qualquer pesquisa. Contar
        cada vazio como "mantido" faria a tela dizer "manteve 60 campos do gabarito" numa
        ficha que tem **um** valor. O que se mantém é valor, não ausência.
        """
        primeira = _gravar(sessao, _resultado(_spec(**FICHA)))
        assert primeira.fusao is None or primeira.fusao.mantidos == 0

        segunda = _gravar(
            sessao,
            _resultado(_spec(**{"dimensoes.tanque_l": (80, "l", "80 litros")}), texto=TEXTO_TANQUE),
            job_id=_job_de_pesquisa(sessao),
        )
        assert segunda.fusao.mantidos == len(FICHA), (
            "só os campos que já tinham valor contam como mantidos"
        )

    def test_pesquisa_que_nao_fechou_nada_mantem_a_ficha_anterior(self, sessao):
        from api.app.models import SpecValue

        primeira = _gravar(sessao, _resultado(_spec(**FICHA)))
        segunda = _gravar(sessao, _resultado(_spec()))

        assert segunda.ficha_mantida and segunda.apagados == 0
        assert any("mantida" in a for a in segunda.avisos)
        potencia = sessao.exec(
            select(SpecValue).where(
                SpecValue.version_id == primeira.version_id, SpecValue.field == "potencia_cv"
            )
        ).one()
        assert potencia.value_json == 205

    def test_primeira_pesquisa_vazia_nao_grava_ficha_vazia(self, sessao):
        """55 linhas `nao_encontrado` fariam o Benchmark achar que o carro tem ficha."""
        from api.app.models import SpecValue, Version
        from api.app.routers.benchmark import _versoes_do_modelo

        saida = _gravar(sessao, _resultado(_spec()))
        assert saida.version_id and sessao.get(Version, saida.version_id) is not None
        assert sessao.exec(select(SpecValue)).all() == []
        assert _versoes_do_modelo(sessao, "Mitsubishi", "Triton", 2026) == []
        assert any("sem ficha" in a for a in saida.avisos)


class TestAsBloqueadas:
    def test_fonte_bloqueada_vira_estado_e_alerta(self, sessao):
        from api.app.models import Alert, Source

        fontes = [
            run.Fonte(url=URL, tier=1, motivo="oficial", consulta="q", texto=TEXTO, baixada=True),
            run.Fonte(
                url=BLOQUEADA,
                tier=1,
                motivo="oficial",
                consulta="q",
                bloqueada=True,
                erro="bloqueada",
            ),
        ]
        saida = _gravar(sessao, _resultado(_spec(**FICHA), fontes=fontes))
        # Dois alertas: a fonte bloqueada e a versao nova, que a pesquisa acabou de criar.
        assert saida.alerts == 2
        bloqueada = sessao.exec(select(Source).where(Source.url == BLOQUEADA)).one()
        assert bloqueada.status == "bloqueada"
        alerta = sessao.exec(select(Alert).where(Alert.type == "fonte_bloqueada")).one()
        assert alerta.version_id == saida.version_id


class TestForaDoReplay:
    def test_a_copia_da_pagina_vai_para_o_disco(self, sessao, monkeypatch):
        from api.app.models import Snapshot

        monkeypatch.setenv("REPLAY_MODE", "0")
        # O nome completo do teste + --basetemp pode estourar MAX_PATH no Windows.
        # Esta fixture ainda exercita a escrita real, numa raiz temporária curta.
        with TemporaryDirectory(prefix="specradar-") as root:
            monkeypatch.setenv("SNAPSHOT_DIR", root)
            saida = _gravar(sessao, _resultado(_spec(**FICHA)))
            snap = sessao.exec(select(Snapshot)).one()
            assert snap.text_path and Path(snap.text_path).exists()
            assert Path(snap.text_path).read_text(encoding="utf-8") == TEXTO
            assert saida.snapshots == 1


class TestOAlertaDeVersaoNova:
    """`versao_nova` existe no enum, na tela, nas reacoes — e ninguem emitia.

    O tipo esta em `AlertType`, `pipeline/radar/reactions.py` tem a linha para ele e o
    Radar ja sabe desenhar o icone e o rotulo. O que faltava era o emissor: quando a
    pesquisa cria uma versao que o catalogo nao tinha, isso e exatamente a noticia que o
    Radar existe para dar — "apareceu uma versao que voce nao acompanhava".

    `persistir_pesquisa` ja sabia `criou_versao`; so nao contava a ninguem.
    """

    def test_versao_criada_pela_pesquisa_vira_alerta(self, sessao):
        from api.app.models import Alert

        saida = _gravar(sessao, _resultado(_spec(**FICHA)), job_id=_job_de_pesquisa(sessao))
        assert saida.criou_versao

        alertas = sessao.exec(select(Alert).where(Alert.type == "versao_nova")).all()
        assert len(alertas) == 1
        alerta = alertas[0]
        assert alerta.version_id == saida.version_id
        assert alerta.new["nome"] == "HPE-S"
        assert alerta.new["ano_modelo"] == 2026
        assert alerta.new["origem"] == "pesquisa"
        assert alerta.reactions_json, "o Radar mostra a reacao por area"
        assert saida.alerts >= 1

    def test_versao_que_ja_existia_nao_alerta(self, sessao):
        from api.app.models import Alert

        _gravar(sessao, _resultado(_spec(**FICHA)))
        _gravar(sessao, _resultado(_spec(**FICHA)), job_id=_job_de_pesquisa(sessao))
        alertas = sessao.exec(select(Alert).where(Alert.type == "versao_nova")).all()
        assert len(alertas) == 1, "a segunda pesquisa nao cria a versao de novo"


class TestMarcaEModeloCanonicos:
    """O Benchmark casa por texto exato; 'mitsubishi motors' nao e 'Mitsubishi'.

    `segments.yaml` e `benchmark._versoes_do_modelo` comparam nome de marca e de modelo
    como texto. Uma pesquisa que grave 'MITSUBISHI MOTORS' cria uma segunda marca ao lado
    da que existe, e o carro pesquisado fica invisivel para a comparacao — com ficha, com
    evidencia e fora do benchmark.
    """

    def test_marca_existente_e_reaproveitada(self, sessao):
        from api.app.models import Brand

        primeira = _gravar(sessao, _resultado(_spec(**FICHA)))
        segunda = _gravar(
            sessao,
            _resultado(_spec(**FICHA)),
            marca="  MITSUBISHI   motors ",
            modelo="triton",
        )
        marcas = sessao.exec(select(Brand)).all()
        assert len(marcas) == 1, [m.nome for m in marcas]
        assert segunda.version_id == primeira.version_id

    def test_marca_nova_entra_como_veio(self, sessao):
        from api.app.models import Brand

        _gravar(sessao, _resultado(_spec(**FICHA)), marca="RAM", modelo="Rampage")
        nomes = {m.nome for m in sessao.exec(select(Brand)).all()}
        assert "RAM" in nomes
