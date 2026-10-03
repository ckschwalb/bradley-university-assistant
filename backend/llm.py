"""
Chat model providers. The provider, model and API keys are chosen in the admin dashboard
(Assistant page) and stored in the database; nothing here reads environment variables.
"""

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional

from langchain.chat_models import init_chat_model
from langchain_core.language_models.chat_models import BaseChatModel

from settings_store import JUDGE, LLM, get_setting

# Keys are LangChain's provider names for init_chat_model
PROVIDERS: Dict[str, Dict[str, str]] = {
    "anthropic": {"label": "Claude (Anthropic)", "default_model": "claude-haiku-4-5-20251001",
                  "key_url": "https://console.anthropic.com/settings/keys"},
    "openai": {"label": "OpenAI", "default_model": "gpt-4o-mini",
               "key_url": "https://platform.openai.com/api-keys"},
    "google_genai": {"label": "Gemini (Google)", "default_model": "gemini-2.5-flash",
                     "key_url": "https://aistudio.google.com/apikey"},
}

logger = logging.getLogger(__name__)

TEMPERATURE = 0.3  # low: answers should stick to the retrieved context
JUDGE_TEMPERATURE = 0.0  # the same answer should get the same scores
MAX_TOKENS = 2048
REQUEST_TIMEOUT = 60  # seconds per attempt (2 attempts max); the chat widget waits 130
MAX_RETRIES = 1

PROBE_TOKENS = 16  # a probe asks for just enough output to be accepted by every provider
PROBE_TIMEOUT = 20  # seconds
PROBE_WORKERS = 8
PROBE_CACHE_SECONDS = 6 * 60 * 60  # how long a model's answer to "does it work?" is remembered
MAX_PROBED_MODELS = 100

_probe_cache: Dict[tuple, tuple] = {}  # (provider, model, key) -> (works, when checked)
_models: Dict[tuple, BaseChatModel] = {}
_models_lock = threading.Lock()


class ProviderNotConfigured(Exception):
    """No provider selected, or the selected provider has no API key"""


def list_models(provider: str, api_key: str) -> List[str]:
    """Chat models the key can use, newest first where the API says. Raises if the key is rejected."""
    if provider == "anthropic":
        import anthropic
        return [m.id for m in anthropic.Anthropic(api_key=api_key).models.list(limit=100)]
    if provider == "openai":
        import openai
        ids = [m.id for m in openai.OpenAI(api_key=api_key).models.list()]
        chat = [i for i in ids if i.startswith(("gpt-", "o1", "o3", "o4", "chatgpt"))
                and not any(x in i for x in ("audio", "realtime", "transcribe", "tts", "image", "search"))]
        return sorted(chat, reverse=True)
    if provider == "google_genai":
        from google import genai
        models = genai.Client(api_key=api_key).models.list()
        return [m.name.removeprefix("models/") for m in models
                if "generateContent" in (m.supported_actions or []) and "gemini" in m.name]
    raise ValueError(f"Unknown provider: {provider}")


def _probe(provider: str, model: str, api_key: str) -> bool:
    """Whether the model answers a one-word prompt, with the same settings chats use. False only when the
    provider says the request itself can't work (a retired or non-chat model, or settings it rejects);
    a bad key, rate limit, timeout or outage says nothing about the model, so those count as working."""
    extra = {"stream_usage": True} if provider == "openai" else {}
    try:
        init_chat_model(
            model, model_provider=provider, api_key=api_key, temperature=TEMPERATURE,
            max_tokens=PROBE_TOKENS, timeout=PROBE_TIMEOUT, max_retries=0, **extra,
        ).invoke("Hi")
        return True
    except Exception as e:
        status = getattr(e, "status_code", None) or getattr(e, "code", None)
        if isinstance(status, int) and status in (400, 404, 410):
            logger.info(f"Leaving {provider} model {model} out: {type(e).__name__}: {str(e)[:200]}")
            return False
        return True


def available_models(provider: str, api_key: str) -> List[str]:
    """list_models without the models that no longer work: the providers' lists still include retired
    and non-chat models, so each one is tried once (in parallel) and remembered for a few hours."""
    candidates = list_models(provider, api_key)[:MAX_PROBED_MODELS]
    now = time.time()
    unknown = [m for m in candidates
               if (cached := _probe_cache.get((provider, m, api_key))) is None or now - cached[1] > PROBE_CACHE_SECONDS]
    if unknown:
        with ThreadPoolExecutor(max_workers=PROBE_WORKERS) as pool:
            for model, works in zip(unknown, pool.map(lambda m: _probe(provider, m, api_key), unknown), strict=True):
                _probe_cache[(provider, model, api_key)] = (works, now)
    return [m for m in candidates if _probe_cache[(provider, m, api_key)][0]]


def active_selection() -> Optional[Dict[str, str]]:
    """{provider, model, api_key} for the selected provider, or None if not usable yet"""
    config = get_setting(LLM)
    provider = config.get("provider")
    api_key = (config.get("api_keys") or {}).get(provider)
    if provider not in PROVIDERS or not api_key:
        return None
    model = (config.get("models") or {}).get(provider) or PROVIDERS[provider]["default_model"]
    return {"provider": provider, "model": model, "api_key": api_key}


def judge_selection() -> Optional[Dict[str, str]]:
    """{provider, model, api_key} for the quality judge, or None when it's off or no provider is set up.
    The judge uses the chat provider's key, with its own model if one is chosen (Assistant page)."""
    selection = active_selection()
    config = get_setting(JUDGE)
    if selection is None or not config.get("enabled", True):
        return None
    model = (config.get("models") or {}).get(selection["provider"]) or selection["model"]
    return {**selection, "model": model}


def _model_for(selection: Dict[str, str], temperature: float) -> BaseChatModel:
    cache_key = (selection["provider"], selection["model"], selection["api_key"], temperature)
    with _models_lock:
        if cache_key not in _models:
            if len(_models) >= 4:
                _models.clear()  # only the current chat and judge models are ever used
            extra = {"stream_usage": True} if selection["provider"] == "openai" else {}  # token counts when streaming
            _models[cache_key] = init_chat_model(
                selection["model"], model_provider=selection["provider"], api_key=selection["api_key"],
                temperature=temperature, max_tokens=MAX_TOKENS,
                timeout=REQUEST_TIMEOUT, max_retries=MAX_RETRIES, **extra,
            )
        return _models[cache_key]


def get_chat_model() -> tuple:
    """(chat model, selection) for the provider chosen in the dashboard"""
    selection = active_selection()
    if selection is None:
        raise ProviderNotConfigured()
    return _model_for(selection, TEMPERATURE), selection


def get_judge_model() -> tuple:
    """(judge model, selection), or raises ProviderNotConfigured when the judge is off"""
    selection = judge_selection()
    if selection is None:
        raise ProviderNotConfigured()
    return _model_for(selection, JUDGE_TEMPERATURE), selection
