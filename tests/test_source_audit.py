from datetime import date

from llm_preflight import retirements
from llm_preflight.source_audit import audit_source, audit_source_text

TODAY = date(2026, 10, 9)


def _without_retirement(references):
    return [{k: v for k, v in item.items() if k != "retirement"} for item in references]


def test_source_audit_reports_literal_model_ids_without_network(tmp_path):
    (tmp_path / "app.py").write_text(
        'fast = "gpt-5.4-mini"\nlegacy = "claude-3-opus"\n'
    )

    report = audit_source(tmp_path, today=TODAY)

    assert report["network_accessed"] is False
    assert _without_retirement(report["references"]) == [
        {
            "path": "app.py",
            "line": 1,
            "provider": "openai",
            "model": "gpt-5.4-mini",
            "status": "pricing_known",
            "confidence": "official_snapshot",
        },
        {
            "path": "app.py",
            "line": 2,
            "provider": "anthropic",
            "model": "claude-3-opus",
            "status": "pricing_unknown",
            "confidence": "unknown",
        },
    ]
    assert report["references"][0]["retirement"]["status"] == "unknown"
    assert report["ok"] is True
    assert report["confidence"] == "limited_static_pricing_and_retirement"
    assert report["retirement_snapshot"]["providers"] == ["anthropic", "openai"]
    assert any("not a verdict" in note for note in report["notes"])


def test_source_audit_detects_provider_prefixed_and_unquoted_yaml_model_ids(tmp_path):
    (tmp_path / "models.yaml").write_text(
        "model: gpt-5.5\nmodel: anthropic/claude-sonnet-5\nmodel: x-ai/grok-4.3\n"
        "model: deepseek-flash\nmodel: qwen3.8-max\nmodel: jev-latest\n"
    )

    report = audit_source(tmp_path)

    assert [(item["line"], item["model"]) for item in report["references"]] == [
        (1, "gpt-5.5"),
        (2, "anthropic/claude-sonnet-5"),
        (3, "x-ai/grok-4.3"),
        (4, "deepseek-flash"),
        (5, "qwen3.8-max"),
        (6, "jev-latest"),
    ]


def test_source_audit_ignores_bare_model_prefix_fragments(tmp_path):
    (tmp_path / "app.py").write_text('prefix = "gpt-"\nother = "claude-"\n')

    assert audit_source(tmp_path)["references"] == []


def test_source_audit_recognizes_glm_5_3_and_routed_id(tmp_path):
    (tmp_path / "app.py").write_text('native = "glm-5.3"\nrouted = "z-ai/glm-5.3"\n')
    report = audit_source(tmp_path)
    assert [r["model"] for r in report["references"]] == ["glm-5.3", "z-ai/glm-5.3"]
    assert all(r["provider"] == "zai" for r in report["references"])
    assert report["references"][0]["status"] == "pricing_known"


def test_source_audit_ignores_paths_and_commented_yaml(tmp_path):
    (tmp_path / "app.py").write_text('path = "docs/gpt-4-notes.md"\n')
    (tmp_path / "models.yaml").write_text("# model: gpt-4o-mini\n")

    assert audit_source(tmp_path)["references"] == []


URL = "https://example.test/deprecations"
TABLE = {
    ("openai", "gpt-gone"): {
        "status": "deprecated",
        "retirement_date": "2026-10-01",
        "replacement": "gpt-new",
        "as_of": "2026-10-01",
        "source_url": URL,
    },
    ("openai", "gpt-going"): {
        "status": "deprecated",
        "retirement_date": "2027-04-01",
        "as_of": "2026-10-01",
        "source_url": URL,
    },
    ("openai", "gpt-new"): {
        "status": "active",
        "as_of": "2026-10-01",
        "source_url": URL,
    },
    ("anthropic", "claude-fine"): {
        "status": "active",
        "as_of": "2026-10-01",
        "source_url": URL,
    },
}


def test_source_audit_attaches_retirement_verdicts_and_a_decision(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(retirements, "PUBLIC_RETIREMENTS", TABLE)
    (tmp_path / "app.py").write_text(
        'a = "gpt-gone"\nb = "gpt-going"\nc = "claude-fine"\nd = "gpt-mystery"\n'
    )
    (tmp_path / "other.py").write_text('e = "gpt-gone"\n')

    report = audit_source(tmp_path, today=TODAY)

    by_model = {item["model"]: item["retirement"] for item in report["references"]}
    assert by_model["gpt-gone"]["status"] == "retired"
    assert by_model["gpt-going"]["status"] == "retiring"
    assert by_model["claude-fine"]["status"] == "active"
    assert by_model["gpt-mystery"]["status"] == "unknown"
    assert report["decision"] == "fail"
    assert [(f["path"], f["model"]) for f in report["findings"]] == [
        ("app.py", "gpt-gone"),
        ("app.py", "gpt-going"),
        ("app.py", "claude-fine"),
        ("app.py", "gpt-mystery"),
        ("other.py", "gpt-gone"),
    ]
    assert report["next_commands"] == [
        'llm-preflight --quick "<your prompt>" --models openai:gpt-gone,openai:gpt-new --dry-run'
    ]


def test_source_audit_findings_exclude_priced_models_with_unknown_retirement(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(retirements, "PUBLIC_RETIREMENTS", TABLE)
    (tmp_path / "app.py").write_text('fast = "gpt-5.4-mini"\n')

    report = audit_source(tmp_path, today=TODAY)

    assert report["references"][0]["status"] == "pricing_known"
    assert report["findings"] == []
    assert report["decision"] == "none"


def test_source_audit_is_inconclusive_when_only_retiring_ids_are_found(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(retirements, "PUBLIC_RETIREMENTS", TABLE)
    (tmp_path / "app.py").write_text('b = "gpt-going"\n')

    assert audit_source(tmp_path, today=TODAY)["decision"] == "inconclusive"


def test_source_audit_text_carries_the_same_fields(tmp_path, monkeypatch):
    monkeypatch.setattr(retirements, "PUBLIC_RETIREMENTS", TABLE)

    report = audit_source_text(tmp_path / "app.py", 'a = "gpt-gone"\n', today=TODAY)

    assert report["references"][0]["retirement"]["status"] == "retired"
    assert report["decision"] == "fail"
    assert report["next_commands"]
    assert report["confidence"] == "limited_static_pricing_and_retirement"


def test_source_audit_defaults_today_to_the_current_date(tmp_path):
    (tmp_path / "app.py").write_text('a = "gpt-5.4-mini"\n')
    assert audit_source(tmp_path)["decision"] in {
        "none",
        "pass",
        "inconclusive",
        "fail",
    }
