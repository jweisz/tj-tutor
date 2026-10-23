"""App configuration: recipe.toml > built-in defaults. recipe.toml is read via
TJBot.get_recipe_config(), which only parses TOML and never constructs a
TJBot or touches hardware."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from tutor.llm.factory import ProviderConfig


class AppConfig(BaseModel):
    lesson_path: Path = Path("lessons/space_basics.yaml")
    interface: Literal["console", "tjbot"] = "console"
    provider: ProviderConfig = Field(default_factory=ProviderConfig)
    thinking_delay_secs: float = 3.0
    listen_reprompt_secs: float = 5.0


def load_app_config(recipe_config_path: str = "recipe.toml") -> AppConfig:
    config = AppConfig()
    tutor_section = _read_recipe_tutor_section(recipe_config_path)
    if tutor_section:
        config = _apply_recipe_section(config, tutor_section)
    return config


def _read_recipe_tutor_section(recipe_config_path: str) -> dict[str, Any]:
    try:
        from tjbot import TJBot
    except ImportError:
        return {}
    try:
        full_recipe = TJBot.get_recipe_config(recipe_config_path)
    except Exception:
        # Missing/malformed recipe.toml shouldn't prevent running with defaults.
        return {}
    if not isinstance(full_recipe, dict):
        return {}
    tutor_section = full_recipe.get("tutor", {})
    return tutor_section if isinstance(tutor_section, dict) else {}


def _apply_recipe_section(config: AppConfig, tutor_section: dict[str, Any]) -> AppConfig:
    data = config.model_dump()
    if "lesson_path" in tutor_section:
        data["lesson_path"] = tutor_section["lesson_path"]
    if "interface" in tutor_section:
        data["interface"] = tutor_section["interface"]
    if "thinking_delay_secs" in tutor_section:
        data["thinking_delay_secs"] = float(tutor_section["thinking_delay_secs"])
    if "listen_reprompt_secs" in tutor_section:
        data["listen_reprompt_secs"] = float(tutor_section["listen_reprompt_secs"])

    llm_section = tutor_section.get("llm", {})
    if isinstance(llm_section, dict) and llm_section:
        provider_data = dict(data["provider"])
        if "provider" in llm_section:
            provider_data["kind"] = llm_section["provider"]
        if "anthropic_effort" in llm_section:
            provider_data["effort"] = llm_section["anthropic_effort"]
        if "ollama_host" in llm_section:
            provider_data["ollama_host"] = llm_section["ollama_host"]
        if "lmstudio_host" in llm_section:
            provider_data["lmstudio_host"] = llm_section["lmstudio_host"]
        if "lmstudio_reasoning" in llm_section:
            provider_data["lmstudio_reasoning"] = llm_section["lmstudio_reasoning"]
        # model is provider-specific, so pick the key matching the (possibly
        # just-updated) provider kind rather than a single shared "model" key.
        kind = provider_data["kind"]
        if kind == "ollama" and "ollama_model" in llm_section:
            provider_data["model"] = llm_section["ollama_model"]
        elif kind == "anthropic" and "anthropic_model" in llm_section:
            provider_data["model"] = llm_section["anthropic_model"]
        elif kind == "lmstudio" and "lmstudio_model" in llm_section:
            provider_data["model"] = llm_section["lmstudio_model"] or None
        data["provider"] = provider_data

    return AppConfig.model_validate(data)
