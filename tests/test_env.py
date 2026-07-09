import os

from llm_bench.env import load_env_file


def test_loads_production_env_without_overwriting_existing_value(tmp_path, monkeypatch):
    path = tmp_path / ".env.production"
    path.write_text(
        'OPENAI_API_KEY="from-file"\n'
        "GEMINI_API_KEY='gemini-file'\n"
        "# ignored comment\n"
    )
    monkeypatch.setenv("OPENAI_API_KEY", "already-set")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    load_env_file(path)

    assert os.environ["OPENAI_API_KEY"] == "already-set"
    assert os.environ["GEMINI_API_KEY"] == "gemini-file"


def test_missing_env_file_is_allowed(tmp_path):
    load_env_file(tmp_path / ".env.production")
