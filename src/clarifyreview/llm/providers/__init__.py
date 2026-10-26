"""Backend registry. One entry per provider."""

from __future__ import annotations

from ...config import settings
from ..base import Backend


def build_backend(provider: str | None = None) -> Backend:
    name = provider or settings().provider
    if name == "gemini":
        from .gemini_backend import GeminiBackend

        return GeminiBackend()
    if name == "anthropic":
        from .anthropic_backend import AnthropicBackend

        return AnthropicBackend()
    if name == "ollama":
        from .ollama_backend import OllamaBackend

        return OllamaBackend()
    raise ValueError(
        f"unknown provider: {name!r} (expected 'gemini', 'anthropic' or 'ollama')")
