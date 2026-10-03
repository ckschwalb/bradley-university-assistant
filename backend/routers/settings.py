"""
AI provider settings: which provider answers chats, which model, and the API key for each; and
whether the quality judge grades each answer, with which model.
"""

import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth import require_admin
from llm import PROVIDERS, available_models
from settings_store import JUDGE, LLM, get_setting, set_setting

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/settings", tags=["settings"], dependencies=[Depends(require_admin)])


class ProviderUpdate(BaseModel):
    provider: str
    model: Optional[str] = None
    api_key: Optional[str] = None  # omitted: keep the saved key; empty string: remove it


class JudgeUpdate(BaseModel):
    enabled: bool
    model: Optional[str] = None  # for the chat provider; empty: use the chat model


class ModelsRequest(BaseModel):
    provider: str
    api_key: Optional[str] = None  # omitted: use the saved key


def key_hint(key: Optional[str]) -> Optional[str]:
    return f"…{key[-4:]}" if key else None


def llm_settings_view() -> dict:
    """Settings for the dashboard. Saved keys are never sent back, only their last 4 characters."""
    config = get_setting(LLM)
    keys, models = config.get("api_keys") or {}, config.get("models") or {}
    return {
        "provider": config.get("provider"),
        "providers": [
            {
                "id": provider_id,
                "label": info["label"],
                "default_model": info["default_model"],
                "model": models.get(provider_id) or info["default_model"],
                "has_key": bool(keys.get(provider_id)),
                "key_hint": key_hint(keys.get(provider_id)),
                "key_url": info["key_url"],
            }
            for provider_id, info in PROVIDERS.items()
        ],
    }


def check_provider(provider: str):
    if provider not in PROVIDERS:
        raise HTTPException(status_code=400, detail=f"Unknown provider '{provider}'")


@router.get("/llm")
async def get_llm_settings():
    return llm_settings_view()


@router.put("/llm")
async def update_llm_settings(update: ProviderUpdate):
    """Select a provider, and optionally set its model and API key"""
    check_provider(update.provider)
    config = get_setting(LLM)
    keys, models = dict(config.get("api_keys") or {}), dict(config.get("models") or {})
    if update.api_key is not None:
        if update.api_key.strip():
            keys[update.provider] = update.api_key.strip()
        else:
            keys.pop(update.provider, None)
    if update.model:
        models[update.provider] = update.model.strip()
    set_setting(LLM, {"provider": update.provider, "api_keys": keys, "models": models})
    return llm_settings_view()


def judge_view() -> dict:
    """The judge for the current chat provider: whether it's on and which model it uses"""
    config, llm = get_setting(JUDGE), get_setting(LLM)
    provider = llm.get("provider")
    chat_model = (llm.get("models") or {}).get(provider) or PROVIDERS.get(provider, {}).get("default_model")
    chosen = (config.get("models") or {}).get(provider)
    return {"enabled": config.get("enabled", True), "provider": provider, "model": chosen or chat_model,
            "same_as_chat": not chosen or chosen == chat_model}


@router.get("/judge")
async def get_judge_settings():
    return judge_view()


@router.put("/judge")
async def update_judge_settings(update: JudgeUpdate):
    config = get_setting(JUDGE)
    models = dict(config.get("models") or {})
    provider = get_setting(LLM).get("provider")
    if provider:
        if update.model and update.model.strip():
            models[provider] = update.model.strip()
        else:
            models.pop(provider, None)
    set_setting(JUDGE, {"enabled": update.enabled, "models": models})
    return judge_view()


@router.post("/llm/models")
async def get_provider_models(request: ModelsRequest):
    """List the working chat models a key can use. Also serves as the key check before saving."""
    check_provider(request.provider)
    api_key = (request.api_key or "").strip() or (get_setting(LLM).get("api_keys") or {}).get(request.provider)
    if not api_key:
        raise HTTPException(status_code=400, detail="Enter an API key first")
    try:
        models = await asyncio.to_thread(available_models, request.provider, api_key)
    except Exception as e:
        status = getattr(e, "status_code", None) or getattr(e, "code", None)
        logger.warning(f"Listing {request.provider} models failed: {type(e).__name__}: {e}")
        detail = "The API key was rejected" if status in (400, 401, 403) else f"Couldn't reach the provider ({type(e).__name__})"
        raise HTTPException(status_code=400, detail=detail) from e
    return {"models": models, "default_model": PROVIDERS[request.provider]["default_model"]}
