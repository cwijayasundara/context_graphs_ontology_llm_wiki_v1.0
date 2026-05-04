from __future__ import annotations

import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agents"))

from llm import get_llm  # noqa: E402


def test_moonshot_disables_thinking_for_tool_call_compatibility(monkeypatch):
    monkeypatch.setenv("MOONSHOT_API_KEY", "test-key")
    monkeypatch.setenv("KIMI_TEMPERATURE", "1")

    llm = get_llm(provider="moonshot")

    assert llm.extra_body == {"thinking": {"type": "disabled"}}


def test_moonshot_uses_instant_mode_temperature_by_default(monkeypatch):
    monkeypatch.setenv("MOONSHOT_API_KEY", "test-key")
    monkeypatch.setenv("KIMI_TEMPERATURE", "1")

    llm = get_llm(provider="moonshot")

    assert llm.temperature == 0.6


def test_openai_provider_uses_openai_key_and_model(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-5.2")

    llm = get_llm(provider="openai")

    assert llm.model_name == "gpt-5.2"
    assert llm.openai_api_key.get_secret_value() == "test-openai-key"


def test_gemini_provider_uses_google_genai_adapter(monkeypatch):
    class FakeGemini:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    fake_module = types.SimpleNamespace(ChatGoogleGenerativeAI=FakeGemini)
    monkeypatch.setitem(sys.modules, "langchain_google_genai", fake_module)
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-3-pro-preview")

    llm = get_llm(provider="gemini")

    assert isinstance(llm, FakeGemini)
    assert llm.kwargs["model"] == "gemini-3-pro-preview"
    assert llm.kwargs["google_api_key"] == "test-gemini-key"


def test_gemini_provider_reports_missing_dependency(monkeypatch):
    monkeypatch.setitem(sys.modules, "langchain_google_genai", None)
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")

    try:
        get_llm(provider="gemini")
    except RuntimeError as exc:
        assert "langchain-google-genai" in str(exc)
    else:
        raise AssertionError("expected RuntimeError for missing Gemini dependency")


def test_deepseek_disables_thinking_for_tool_call_compatibility(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-deepseek-key")

    llm = get_llm(provider="deepseek", model="deepseek-v4-pro")

    assert llm.extra_body == {"thinking": {"type": "disabled"}}
