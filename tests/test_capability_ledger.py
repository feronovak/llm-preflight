import pytest

from llm_preflight.capability_ledger import (
    apply_probe_evidence,
    load_ledger,
    record_probe,
)


def test_probe_ledger_records_account_specific_evidence(tmp_path):
    path = tmp_path / "capabilities.json"

    record_probe(
        path,
        {
            "provider": "openai",
            "model": "gpt-test",
            "adapter": "openai_responses",
            "outcome": "text-ready",
            "fingerprint": "version-1",
            "request_options": {"max_output_tokens": 32},
        },
    )

    ledger = load_ledger(path)

    assert ledger["schema_version"] == 1
    assert ledger["probes"]["openai:gpt-test"]["outcome"] == "text-ready"
    assert ledger["probes"]["openai:gpt-test"]["request_options"] == {
        "max_output_tokens": 32
    }
    assert path.stat().st_mode & 0o077 == 0


def test_load_ledger_rejects_an_unsupported_schema_version(tmp_path):
    path = tmp_path / "capabilities.json"
    path.write_text('{"schema_version": 2, "probes": {}}')

    with pytest.raises(ValueError, match="invalid capability ledger"):
        load_ledger(path)


def test_load_ledger_rejects_a_non_dict_probes_field(tmp_path):
    path = tmp_path / "capabilities.json"
    path.write_text('{"schema_version": 1, "probes": []}')

    with pytest.raises(ValueError, match="invalid capability ledger probes"):
        load_ledger(path)


def test_record_probe_requires_provider_and_model(tmp_path):
    path = tmp_path / "capabilities.json"

    with pytest.raises(ValueError, match="requires provider and model"):
        record_probe(path, {"provider": "openai"})


def test_record_probe_cleans_up_the_temp_file_when_the_payload_cannot_be_written(
    tmp_path,
):
    path = tmp_path / "capabilities.json"

    with pytest.raises(TypeError):
        record_probe(
            path,
            {
                "provider": "openai",
                "model": "gpt-test",
                "outcome": "text-ready",
                # A set is not JSON-serializable, forcing json.dump to fail mid-write.
                "request_options": {"bad", "value"},
            },
        )

    assert not any(tmp_path.glob(".*capabilities.json.*.tmp"))
    assert not path.exists()


def test_apply_probe_evidence_enriches_a_matching_probe(tmp_path):
    path = tmp_path / "capabilities.json"
    record_probe(
        path,
        {
            "provider": "openai",
            "model": "gpt-test",
            "adapter": "openai_responses",
            "outcome": "text-ready",
            "fingerprint": "version-1",
        },
    )

    models = apply_probe_evidence(
        [
            {
                "provider": "openai",
                "model": "gpt-test",
                "catalog_type": "text-candidate",
                "capabilities": {"fingerprint": "version-1"},
            }
        ],
        load_ledger(path),
    )

    model = models[0]
    assert model["catalog_type"] == "text-ready"
    assert model["catalog_confidence"] == "probe"
    assert model["capabilities"]["adapter"] == "openai_responses"
    assert model["capability_evidence"][0]["source"] == "probe"


def test_transient_probe_outcome_does_not_hide_a_model_from_retry(tmp_path):
    path = tmp_path / "capabilities.json"
    record_probe(
        path,
        {
            "provider": "openai",
            "model": "gpt-test",
            "outcome": "indeterminate",
            "error_category": "timeout",
        },
    )

    models = apply_probe_evidence(
        [{"provider": "openai", "model": "gpt-test", "catalog_type": "text-candidate"}],
        load_ledger(path),
    )

    assert models[0]["catalog_type"] == "text-candidate"
