"""Settings that only the live bot cares about.

Kept apart from `config.Settings` so the research code never has to know the bot
exists. It reads the same `.env`; unknown keys are ignored in both directions.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class BotSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_prefix="", extra="ignore", case_sensitive=False
    )

    # Seconds between background sweeps for expired parked runs. 0 turns the loop
    # off (tests, or when `clarifyreview sweep` runs from cron instead).
    clarifyreview_sweep_interval_s: float = 300.0
    # The account the bot comments as. Empty means: look it up once with GET /user
    # (personal access token), or rely on the "Bot" account type (GitHub App).
    clarifyreview_bot_login: str = ""
    clarifyreview_review_on_push: bool = True
    clarifyreview_skip_drafts: bool = True
    # GitHub rejects comments over 65,536 characters; stay well under.
    clarifyreview_max_comment_chars: int = 60000
    # What the `runs.condition` column says for production runs, so they can never
    # be mistaken for a Study A condition.
    clarifyreview_bot_condition: str = "github_live"

    github_api_url: str = "https://api.github.com"
    # Optional GitHub App credentials. Without them the bot uses GITHUB_TOKEN.
    github_app_id: str = ""
    github_app_private_key_path: str = ""


_bot_settings: BotSettings | None = None


def bot_settings() -> BotSettings:
    global _bot_settings
    if _bot_settings is None:
        _bot_settings = BotSettings()
    return _bot_settings


def reset_bot_settings() -> None:
    """Test hook: drop the cached singleton so env changes take effect."""
    global _bot_settings
    _bot_settings = None
