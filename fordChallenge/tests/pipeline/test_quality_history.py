from itertools import permutations

from sqlmodel import Session, SQLModel, create_engine, select

from api.app.models import Brand, FieldDecision, FieldObservation, VehicleModel, Version
from api.app.services.spec_assembler import montar
from pipeline.persist import fundir_valores
from pipeline.publication import choose
from pipeline.schema import Evidence, SpecField, Status, empty_spec


def cell(value, tier=1, url="https://ford.com.br/ficha"):
    return SpecField.verificado(
        value,
        Evidence(
            evidence_id=url,
            source_url=url,
            tier=tier,
            quote=f"Potência {value} cv",
            captured_at="2026-09-14",
        ),
        unit="cv",
    )


def test_decisao_independe_da_ordem_e_da_quantidade_de_paginas():
    strong = cell(250)
    weak = cell(200, 3, "https://revista.test/ficha")
    for order in permutations([strong, weak, weak]):
        result = choose("potencia_cv", list(order))
        assert result.status == Status.VERIFICADO
        assert result.value == 250
        assert result.conflicts[0].value == 200


def test_referencia_mensal_nao_apaga_dia_publicado():
    previous = cell("2026-09-10")
    incoming = cell("2026-09")
    for fields in ([previous, incoming], [incoming, previous]):
        assert choose("preco_data", fields).value == "2026-09-10"


def test_rejeicao_publicada_sem_projecao_preserva_observacao_e_estado_na_api():
    db = create_engine("sqlite://")
    SQLModel.metadata.create_all(db)
    with Session(db) as session:
        brand = Brand(nome="Volkswagen")
        session.add(brand)
        session.flush()
        model = VehicleModel(nome="Amarok", brand_id=brand.id)
        session.add(model)
        session.flush()
        version = Version(model_id=model.id, nome_exato="V6 Extreme", ano_modelo=2026)
        session.add(version)
        session.flush()
        spec = empty_spec(job_id="test")
        invalid = cell("255/50 R20")
        invalid.evidences[0].quote = "Dianteiros | 255/50 R20"
        spec.set("exterior.pneus_tipo", invalid)
        fundir_valores(session, version_id=version.id, spec=spec, snapshots={})
        session.commit()
        actual = montar(session, version.id).exterior["pneus_tipo"]
        assert actual.value is None
        assert actual.status == Status.NAO_VERIFICADO
        assert session.exec(select(FieldObservation)).first().payload["value"] == "255/50 R20"
        decision = session.exec(
            select(FieldDecision).where(FieldDecision.field == "pneus_tipo")
        ).first()
        assert decision.payload == actual.model_dump(mode="json")


def test_snapshots_de_urls_longas_e_revisoes_simultaneas_nao_sobrescrevem(tmp_path, monkeypatch):
    from pipeline import snapshots

    monkeypatch.setenv("REPLAY_MODE", "0")
    monkeypatch.setattr(snapshots, "agora_iso", lambda: "2026-09-14T00-00-00Z")
    prefix = "https://www.ford.com.br/picapes/ranger/compare-as-versoes/"
    captures = []
    for suffix, text in [
        ("limited", "Limited 250 cv"),
        ("xlt", "XLT 250 cv"),
        ("limited", "Limited 250 cv revisão"),
    ]:
        captures.append(
            snapshots.escrever_snapshot(
                version_id="ranger",
                url_final=prefix + suffix,
                texto=text,
                tier=1,
                tipo="html",
                raiz=tmp_path,
            )
        )
    assert len({s.caminho for s in captures}) == 3
    for snapshot in captures:
        content = (snapshot.caminho / snapshot.text_path).read_text(encoding="utf-8")
        assert snapshots.sha256_de(content) == snapshot.sha256


def test_historico_idempotente_api_igual_decisao_e_merge_nao_degrada():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        brand = Brand(nome="Ford")
        session.add(brand)
        session.flush()
        model = VehicleModel(nome="Ranger", brand_id=brand.id)
        session.add(model)
        session.flush()
        version = Version(model_id=model.id, nome_exato="Limited 3.0 V6", ano_modelo=2027)
        session.add(version)
        session.flush()
        for value in [cell(250), cell(200, 3, "https://revista.test/ficha")]:
            spec = empty_spec(job_id="test")
            spec.set("motorizacao.potencia_cv", value)
            fundir_valores(session, version_id=version.id, spec=spec, snapshots={})
            session.commit()
        before = len(session.exec(select(FieldDecision)).all())
        fundir_valores(session, version_id=version.id, spec=spec, snapshots={})
        session.commit()
        assert len(session.exec(select(FieldDecision)).all()) == before
        observations = session.exec(select(FieldObservation)).all()
        assert {o.payload["value"] for o in observations} == {200, 250}
        published = montar(session, version.id).motorizacao["potencia_cv"]
        assert published.value == 250 and published.status == Status.VERIFICADO
        decision = session.exec(
            select(FieldDecision)
            .where(FieldDecision.field == "potencia_cv")
            .order_by(FieldDecision.criado_em.desc())
        ).first()
        assert published.model_dump(mode="json") == decision.payload
        from api.app.models import Evidence as EvidenceRow

        for evidence in [*published.evidences, *(c.evidence for c in published.conflicts)]:
            stored = session.get(EvidenceRow, evidence.evidence_id)
            assert stored is not None
            assert stored.quote == evidence.quote
            assert stored.source_url == evidence.source_url


def test_persistencia_dirigida_nao_escolhe_ano_vizinho():
    from types import SimpleNamespace

    from pipeline.persist import resolver_version_id

    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        brand = Brand(nome="Ford")
        session.add(brand)
        session.flush()
        model = VehicleModel(nome="Ranger", brand_id=brand.id)
        session.add(model)
        session.flush()
        older = Version(model_id=model.id, nome_exato="Limited", ano_modelo=2026)
        target = Version(model_id=model.id, nome_exato="Limited", ano_modelo=2027)
        session.add_all([older, target])
        session.flush()
        context = SimpleNamespace(
            marca="Ford", modelo="Ranger", versao="Limited", ano=2027, version_id="", resolucao=None
        )
        assert resolver_version_id(session, context) == target.id
        context.version_id = older.id
        assert resolver_version_id(session, context) is None
