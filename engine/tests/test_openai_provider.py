from pathlib import Path

from frlocal.openai import OpenAI, describe_failure


def test_key_and_base_follow_the_first_env_file_with_a_key(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    app_file, home = tmp_path / "provider.env", tmp_path / ".env"
    home.write_text("OPENAI_API_KEY=sk-home\n")
    client = OpenAI("https://api.openai.com", "wss://api.openai.com", (app_file, home))
    assert (client.api_key(), client.base, client.ws_base) == ("sk-home", "https://api.openai.com", "wss://api.openai.com")
    app_file.write_text("OPENAI_API_KEY=irc_device\nFRLOCAL_OPENAI_BASE=https://copilot.example.com/api/v1/openai/\n")
    assert client.api_key() == "irc_device"
    assert client.base == "https://copilot.example.com/api/v1/openai"
    assert client.ws_base == "wss://copilot.example.com/api/v1/openai"
    app_file.write_text("OPENAI_API_KEY=sk-own\n")  # the user's own key goes straight to OpenAI
    assert (client.api_key(), client.base) == ("sk-own", "https://api.openai.com")


def test_quota_message() -> None:
    assert "allowance is used up" in describe_failure(402)
