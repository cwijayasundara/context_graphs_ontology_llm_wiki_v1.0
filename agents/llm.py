"""LLM factory for OpenAI, Gemini, Kimi (Moonshot), OpenRouter, NVIDIA, and DeepSeek.

Pick a provider with LLM_PROVIDER. Values are read from the process env;
agents/_lib.py loads .env at import time so a `.env` file is enough.

Env vars:
  LLM_PROVIDER         — openai | gemini | moonshot (default) | openrouter | nvidia | deepseek
  KIMI_TEMPERATURE     — default 1.0 (used by OpenRouter, NVIDIA, and DeepSeek)

OpenAI:
  OPENAI_API_KEY, OPENAI_MODEL (default: gpt-5.2), OPENAI_TEMPERATURE

Moonshot (Kimi K2.6 default):
  MOONSHOT_API_KEY, MOONSHOT_BASE_URL, KIMI_MODEL

Gemini:
  GEMINI_API_KEY or GOOGLE_API_KEY, GEMINI_MODEL (default: gemini-3-pro-preview),
  GEMINI_TEMPERATURE

OpenRouter (Nemotron 3 Nano Omni default):
  OPENROUTER_API_KEY, OPENROUTER_BASE_URL, OPENROUTER_MODEL
  OPENROUTER_HTTP_REFERER, OPENROUTER_X_TITLE  (optional ranking headers)

NVIDIA (Nemotron 3 Nano direct via build.nvidia.com OpenAI-compatible endpoint):
  NVIDIA_API_KEY, NVIDIA_BASE_URL (default: https://integrate.api.nvidia.com/v1),
  NVIDIA_MODEL (default: nvidia/nemotron-nano-3)

DeepSeek (V4 default):
  DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL
"""
from __future__ import annotations

import os
from typing import Any

from langchain_openai import ChatOpenAI

import _lib  # noqa: F401  — triggers .env load


def _temperature(override: float | None) -> float:
    if override is not None:
        return override
    return float(os.environ.get("KIMI_TEMPERATURE", "1"))


def _optional_temperature(env_name: str, override: float | None) -> float | None:
    if override is not None:
        return override
    raw = os.environ.get(env_name)
    return None if raw in {None, ""} else float(raw)


def _moonshot_temperature(override: float | None) -> float:
    if override is not None:
        return override
    return float(os.environ.get("MOONSHOT_TEMPERATURE", "0.6"))


def _openai(model: str | None, temperature: float | None) -> ChatOpenAI:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set (check .env)")
    kwargs: dict[str, Any] = {
        "api_key": api_key,
        "model": model or os.environ.get("OPENAI_MODEL", "gpt-5.2"),
    }
    if (temp := _optional_temperature("OPENAI_TEMPERATURE", temperature)) is not None:
        kwargs["temperature"] = temp
    if effort := os.environ.get("OPENAI_REASONING_EFFORT"):
        kwargs["reasoning_effort"] = effort
    return ChatOpenAI(**kwargs)


def _moonshot(model: str | None, temperature: float | None) -> ChatOpenAI:
    api_key = os.environ.get("MOONSHOT_API_KEY")
    if not api_key:
        raise RuntimeError("MOONSHOT_API_KEY is not set (check .env)")
    return ChatOpenAI(
        api_key=api_key,
        base_url=os.environ.get("MOONSHOT_BASE_URL", "https://api.moonshot.ai/v1"),
        model=model or os.environ.get("KIMI_MODEL", "kimi-k2.6"),
        temperature=_moonshot_temperature(temperature),
        extra_body={"thinking": {"type": "disabled"}},
    )


def _gemini(model: str | None, temperature: float | None) -> Any:
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY or GOOGLE_API_KEY is not set (check .env)")
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
    except ImportError as exc:
        raise RuntimeError(
            "Gemini support requires langchain-google-genai. "
            "Install it with: pip install langchain-google-genai"
        ) from exc

    kwargs: dict[str, Any] = {
        "model": model or os.environ.get("GEMINI_MODEL", "gemini-3-pro-preview"),
        "google_api_key": api_key,
    }
    if (temp := _optional_temperature("GEMINI_TEMPERATURE", temperature)) is not None:
        kwargs["temperature"] = temp
    return ChatGoogleGenerativeAI(**kwargs)


def _openrouter(model: str | None, temperature: float | None) -> ChatOpenAI:
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY is not set (check .env)")
    headers: dict[str, str] = {}
    if referer := os.environ.get("OPENROUTER_HTTP_REFERER"):
        headers["HTTP-Referer"] = referer
    if title := os.environ.get("OPENROUTER_X_TITLE"):
        headers["X-Title"] = title
    return ChatOpenAI(
        api_key=api_key,
        base_url=os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
        model=model or os.environ.get(
            "OPENROUTER_MODEL",
            "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
        ),
        temperature=_temperature(temperature),
        default_headers=headers or None,
    )


def _nvidia(model: str | None, temperature: float | None) -> ChatOpenAI:
    api_key = os.environ.get("NVIDIA_API_KEY")
    if not api_key:
        raise RuntimeError("NVIDIA_API_KEY is not set (check .env)")
    return ChatOpenAI(
        api_key=api_key,
        base_url=os.environ.get("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1"),
        model=model or os.environ.get("NVIDIA_MODEL", "nvidia/nemotron-nano-3"),
        temperature=_temperature(temperature),
    )


def _deepseek(model: str | None, temperature: float | None) -> ChatOpenAI:
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        raise RuntimeError("DEEPSEEK_API_KEY is not set (check .env)")
    return ChatOpenAI(
        api_key=api_key,
        base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
        model=model or os.environ.get("DEEPSEEK_MODEL", "deepseek-v4"),
        temperature=_temperature(temperature),
        extra_body={"thinking": {"type": "disabled"}},
    )


_PROVIDERS = {
    "openai": _openai,
    "gemini": _gemini,
    "moonshot": _moonshot,
    "openrouter": _openrouter,
    "nvidia": _nvidia,
    "deepseek": _deepseek,
}


def get_llm(*, provider: str | None = None,
             model: str | None = None,
             temperature: float | None = None) -> Any:
    name = (provider or os.environ.get("LLM_PROVIDER", "moonshot")).lower()
    if name not in _PROVIDERS:
        raise ValueError(f"unknown LLM_PROVIDER {name!r}; expected one of {sorted(_PROVIDERS)}")
    return _PROVIDERS[name](model, temperature)
