"""Cadeia contratual sintética; o ensaio real usa o PDF preservado em reports/."""

import hashlib
import json
from dataclasses import replace

import pytest

from pipeline.connectors import vw_manual_warranty as w
from pipeline.identity import VehicleTarget
from pipeline.publication import choose
from pipeline.reconcile import reconciliar
from pipeline.schema import Status
from scripts.audit_quality import check_proof

URL = (
    "https://www.vw.com.br/idhub/content/dam/onehub_pkw/importers/br/literatura-de-bordo/"
    "manual-amarok/my26/Manual_Amarok_MY26_Brasil.pdf"
)
TARGET = VehicleTarget("Volkswagen", "Amarok", "V6 Extreme", 2026)


@pytest.fixture
def chain_factory(tmp_path, monkeypatch):
    def make(*, years=5, label_year=2026, pdf_url=URL, index_url=w.INDEX_URL, scope=True):
        # Parser stub: unit tests exercise framing/proof/hash. A separate real-PDF
        # rehearsal checks pdfplumber and the original 285-page document end-to-end.
        pages = (
            "Manual de instruções\nAmarok\nV1, R9, Brazil, pt_BR\nEdição 08/2025",
            "Este Manual de instruções - Versão Digital é válido\n"
            + (
                "para todas as versões e modelos disponíveis para este veículo."
                if scope
                else "para outra versão."
            ),
            "Garantia Volkswagen\nCobertura da garantia\n"
            f"A garantia tem duração de {years} anos (já incluído o prazo\n"
            "de garantia legal) para o veículo completo\nVolkswagen do Brasil",
            "II - Prazo de validade\n"
            f"{years} anos após o termo inicial.\n"
            f"Em caso de uso comercial, {years} anos ou 100.000 km.\n"
            "Bateria: 12 meses. Tanque 80 litros.",
        )
        monkeypatch.setattr(w, "_extract_pages", lambda raw: pages)
        pdf = tmp_path / "manual.pdf"
        pdf.write_bytes(b"%PDF-unit-fixture\n" + b"x" * 4096)
        html = (
            f'<a href="{pdf_url}" title="Amarok {label_year} - Manual de instruções">'
            f"Amarok {label_year} - Manual de instruções</a>"
        )
        text = w.build(
            index_html=html,
            index_url=index_url,
            index_captured_at="2026-09-15T02:00:00+00:00",
            pdf_path=pdf,
            pdf_url=pdf_url,
            pdf_captured_at="2026-09-14T23:00:00+00:00",
        )
        return text, pdf

    return make


def test_warranty_reconcile_publish_and_audit_complete_chain(chain_factory, tmp_path):
    text, _ = chain_factory()
    items = w.candidatos(text, URL, TARGET, "chain-source")
    assert len(items) == 1 and items[0].valor == 60
    assert items[0].quote in text and len(items[0].quote) <= 300
    assert items[0].source_text == text and items[0].pagina == 259
    result = reconciliar(items, textos={"chain-source": text}, campos=[w.FIELD], target=TARGET)
    cell = result.decisoes[w.FIELD].spec
    final = choose(
        w.FIELD,
        [cell],
        target=TARGET,
        source_texts={e.evidence_id: text for e in cell.evidences},
        require_source_proof=True,
    )
    assert final.status == Status.VERIFICADO and final.value == 60
    assert "100.000 km" in final.notes and "exceções" in final.notes
    snapshot = tmp_path / "chain.txt"
    snapshot.write_text(text, encoding="utf-8")
    audit = check_proof(
        w.FIELD,
        {
            **final.evidences[0].model_dump(),
            "value": 60,
            "unit": "meses",
            "text_path": str(snapshot),
            "sha256": hashlib.sha256(text.encode()).hexdigest(),
        },
        TARGET,
    )
    assert audit["valid"] and audit["hash_ok"] and audit["grounded"]
    assert audit["applicability"]["status"] == "compativel"


@pytest.mark.parametrize("years", [3, 7])
def test_duration_is_read_not_hardcoded(chain_factory, years):
    text, _ = chain_factory(years=years)
    assert w.candidatos(text, URL, TARGET)[0].valor == years * 12


@pytest.mark.parametrize(
    "target",
    [
        replace(TARGET, ano_modelo=2025),
        replace(TARGET, ano_modelo=2027),
        replace(TARGET, ano_modelo=None),
        replace(TARGET, mercado="AR"),
        replace(TARGET, modelo="Ranger"),
        replace(TARGET, marca="Ford"),
    ],
)
def test_other_identity_does_not_inherit_contract(chain_factory, target):
    text, _ = chain_factory()
    assert w.candidatos(text, URL, target) == []


@pytest.mark.parametrize(
    "url",
    [
        URL.replace("https:", "http:"),
        URL.replace("www.vw.com.br", "user@www.vw.com.br"),
        URL.replace("www.vw.com.br", "www.vw.com.br:invalid"),
        "https://[broken",
        URL.replace("www.vw.com.br", "www.vw.com.br.evil.test"),
        URL + "?year=2026",
        URL.replace("/my26/", "/my25/"),
    ],
)
def test_pdf_url_must_be_official_and_concordant_with_link(chain_factory, url):
    text, _ = chain_factory(pdf_url=url)
    assert w.candidatos(text, url, TARGET) == []


def test_requires_original_index_link_not_filename_or_copyright(chain_factory):
    text, _ = chain_factory(label_year=2025)
    assert w.candidatos(text, URL, TARGET) == []
    text, _ = chain_factory(index_url=w.INDEX_URL.replace("www.vw.com.br", "other.test"))
    assert w.candidatos(text, URL, TARGET) == []
    text, _ = chain_factory(scope=False)
    assert w.candidatos(text, URL, TARGET) == []


def test_entire_pdf_hash_and_original_page_text_are_checked(chain_factory):
    text, pdf = chain_factory()
    assert w.candidatos(text, URL, TARGET)
    raw = pdf.read_bytes()
    pdf.write_bytes(raw[:-1] + b"Y")  # A alteração é depois dos primeiros 2 kB.
    assert not w.candidatos(text, URL, TARGET)
    pdf.write_bytes(raw)
    assert not w.candidatos(text.replace("5 anos", "9 anos"), URL, TARGET)
    magic, header, body = text.split("\n", 2)
    meta = json.loads(header)
    meta["pdf_sha256"] = "0" * 64
    assert not w.candidatos(magic + "\n" + json.dumps(meta) + "\n" + body, URL, TARGET)
    pdf.unlink()
    assert not w.candidatos(text, URL, TARGET)


def test_generic_manual_equipment_cannot_use_warranty_exception(chain_factory):
    text, _ = chain_factory()
    candidate = w.candidatos(text, URL, TARGET, "chain")[0]
    assert not w.supports("tanque_l", TARGET, text, URL, "Tanque 80 litros.", 80)
    assert not w.supports(w.FIELD, TARGET, text, URL, "Bateria: 12 meses.", 12)
    assert not w.supports(w.FIELD, TARGET, text, URL, candidate.quote, 84)
    candidate.campo, candidate.valor, candidate.quote = "tanque_l", 80, "Tanque 80 litros."
    result = reconciliar([candidate], textos={"chain": text}, campos=["tanque_l"], target=TARGET)
    assert result.decisoes["tanque_l"].spec.value is None


def test_offline_revalidation_reader_recognizes_typed_contract_source(chain_factory):
    from pipeline.research.events import Trilha
    from pipeline.research.gaps import Orcamento
    from pipeline.research.planner import Alvo
    from pipeline.research.run import Fonte, Leitor, _documentos_de

    text, _ = chain_factory()
    source = Fonte(
        url=URL,
        tier=1,
        tipo="garantia",
        motivo="prova contratual",
        consulta="offline",
        texto=text,
        baixada=True,
        sha256=hashlib.sha256(text.encode()).hexdigest(),
        captured_at="2026-09-14T23:00:00+00:00",
    )
    target = Alvo(marca="Volkswagen", modelo="Amarok", versao="V6 Extreme", ano=2026)
    reader = Leitor(
        target,
        Orcamento(chamadas_llm=0, paginas=0, rodadas=0, segundos=20),
        Trilha(),
        candidatos={"__fipe__": []},
    )
    documents = _documentos_de([source], target)
    assert documents == []
    spec, _ = reader.ler(documents, campos=[w.FIELD], fontes=[source])
    assert spec.comercial["garantia_meses"].value == 60


def test_corrupt_pdf_parser_error_abstains(chain_factory, monkeypatch):
    from pdfminer.pdfparser import PDFSyntaxError

    text, _ = chain_factory()

    def invalid_pdf(raw):
        raise PDFSyntaxError("corrupted PDF fixture")

    monkeypatch.setattr(w, "_extract_pages", invalid_pdf)
    assert w.read(text) is None
    assert w.candidatos(text, URL, TARGET) == []


def test_applicator_changes_only_warranty_with_rollback_and_backup(chain_factory, tmp_path):
    import sqlite3

    from sqlmodel import Session, SQLModel, create_engine

    from api.app.models import Brand, SpecValue, VehicleModel, Version
    from scripts.apply_vw_manual_warranty import apply_warranty

    text, _ = chain_factory()
    envelope = tmp_path / "chain.txt"
    envelope.write_text(text, encoding="utf-8")
    database = tmp_path / "main.db"
    engine = create_engine("sqlite:///" + database.as_posix())
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Brand(id="brand", nome="Volkswagen"))
        session.add(VehicleModel(id="model", brand_id="brand", nome="Amarok"))
        for vid, trim in [("target", "V6 Extreme"), ("other", "V6 Highline")]:
            session.add(Version(id=vid, model_id="model", nome_exato=trim, ano_modelo=2026))
            session.add(
                SpecValue(
                    version_id=vid,
                    field="potencia_cv",
                    value_json=258,
                    status="nao_verificado",
                    confidence=0.0,
                )
            )
        session.commit()
    engine.dispose()
    before = hashlib.sha256(database.read_bytes()).hexdigest()
    preview = apply_warranty(database, "target", envelope, tmp_path / "preview.json")
    assert preview["ready_to_apply"], preview["errors"]
    assert not preview["applied"] and preview["transaction"] == "rolled_back"
    assert hashlib.sha256(database.read_bytes()).hexdigest() == before
    with pytest.raises(ValueError, match="backup"):
        apply_warranty(database, "target", envelope, tmp_path / "missing-backup.json", apply=True)
    backup = tmp_path / "backup.db"
    applied = apply_warranty(
        database, "target", envelope, tmp_path / "applied.json", apply=True, backup=backup
    )
    assert applied["applied"] and applied["isolation"]["valid"], applied["errors"]
    assert (
        applied["isolation"]["unrelated_before_sha256"]
        == applied["isolation"]["unrelated_after_sha256"]
    )
    assert all(a["valid"] for a in applied["final_audits"])
    with sqlite3.connect(database) as conn:
        assert (
            conn.execute("SELECT count(*) FROM spec_values WHERE field='potencia_cv'").fetchone()[0]
            == 2
        )
        assert (
            conn.execute(
                "SELECT value_json FROM spec_values WHERE field='garantia_meses'"
            ).fetchone()[0]
            == 60
        )
    with sqlite3.connect(backup) as conn:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert (
            conn.execute(
                "SELECT count(*) FROM spec_values WHERE field='garantia_meses'"
            ).fetchone()[0]
            == 0
        )


@pytest.mark.parametrize(
    "old_version,old_field", [("other", "garantia_meses"), ("target", "tanque_l")]
)
def test_fingerprint_rejects_relabeling_an_unrelated_row(old_version, old_field):
    from scripts.apply_vw_manual_warranty import _check_changes

    before = {
        "spec_values": {
            "id": {"hash": "before", "scope": {"version_id": old_version, "field": old_field}}
        }
    }
    after = {
        "spec_values": {
            "id": {"hash": "after", "scope": {"version_id": "target", "field": "garantia_meses"}}
        }
    }
    result = _check_changes(
        before, after, version_id="target", url=URL, quote="proof", snapshot_id="s", digest="d"
    )
    assert not result["valid"] and result["unexpected"]
    assert result["unrelated_before_sha256"] != result["unrelated_after_sha256"]
