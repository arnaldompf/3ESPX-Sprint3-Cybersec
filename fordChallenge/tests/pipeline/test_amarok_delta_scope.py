"""O patch FIPE/ADAS não pode modificar garantia ou outra versão."""

import pytest

from pipeline.schema import empty_spec
from scripts.apply_amarok_quality_delta import DeltaSpec, _isolation


def test_delta_spec_yields_only_the_two_authorized_fields():
    spec = DeltaSpec.model_validate(empty_spec().model_dump())
    assert [path for path, _ in spec.itens()] == [
        "identificacao.codigo_fipe",
        "seguranca.adas_nome_comercial",
    ]


@pytest.mark.parametrize("version,field", [("target", "garantia_meses"), ("other", "codigo_fipe")])
def test_scope_fingerprint_rejects_other_fields_or_vehicles(version, field):
    before = {
        "spec_values": {"id": {"hash": "before", "scope": {"version_id": version, "field": field}}}
    }
    after = {
        "spec_values": {
            "id": {"hash": "after", "scope": {"version_id": "target", "field": "codigo_fipe"}}
        }
    }
    result = _isolation(before, after, "target", set())
    assert not result["valid"]
    assert result["unrelated_before_sha256"] != result["unrelated_after_sha256"]


def test_existing_evidence_and_snapshot_cannot_be_changed():
    original = {
        "hash": "before",
        "scope": {
            "version_id": "target",
            "field": "codigo_fipe",
            "snapshot_id": "s",
            "source_url": "https://example.test",
            "quote": "code",
        },
    }
    changed = {**original, "hash": "after"}
    for table in ["evidences", "snapshots"]:
        result = _isolation(
            {table: {"id": original}},
            {table: {"id": changed}},
            "target",
            {("s", "https://example.test", "code")},
        )
        assert not result["valid"]
