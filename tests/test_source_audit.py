from llm_preflight.source_audit import audit_source


def test_source_audit_reports_literal_model_ids_without_network(tmp_path):
    (tmp_path / "app.py").write_text(
        'fast = "gpt-5.4-mini"\nlegacy = "claude-3-opus"\n'
    )

    report = audit_source(tmp_path)

    assert report["network_accessed"] is False
    assert report["references"] == [
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
    assert report["ok"] is True
    assert report["confidence"] == "limited_static_pricing"


def test_source_audit_detects_provider_prefixed_and_unquoted_yaml_model_ids(tmp_path):
    (tmp_path / "models.yaml").write_text(
        "model: gpt-5.5\nmodel: anthropic/claude-sonnet-5\nmodel: x-ai/grok-4.3\n"
    )

    report = audit_source(tmp_path)

    assert [(item["line"], item["model"]) for item in report["references"]] == [
        (1, "gpt-5.5"),
        (2, "anthropic/claude-sonnet-5"),
        (3, "x-ai/grok-4.3"),
    ]


def test_source_audit_ignores_bare_model_prefix_fragments(tmp_path):
    (tmp_path / "app.py").write_text('prefix = "gpt-"\nother = "claude-"\n')

    assert audit_source(tmp_path)["references"] == []


def test_source_audit_ignores_paths_and_commented_yaml(tmp_path):
    (tmp_path / "app.py").write_text('path = "docs/gpt-4-notes.md"\n')
    (tmp_path / "models.yaml").write_text("# model: gpt-4o-mini\n")

    assert audit_source(tmp_path)["references"] == []
