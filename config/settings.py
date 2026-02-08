"""Application settings via pydantic-settings."""

from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = {"env_prefix": "EIGHT_RACK_"}

    # API keys
    anthropic_api_key: str = ""
    openai_api_key: str = ""

    # Paths
    data_dir: Path = Path("./data")
    config_dir: Path = Path("./config")

    # LLM settings
    llm_budget_limit: float = 25.00
    pilot_model: str = "claude-sonnet-4-5-20250929"
    opponent_model: str = "claude-haiku-4-5-20251001"
    adjudicator_model: str = "claude-sonnet-4-5-20250929"
    tuning_model: str = "claude-opus-4-6"

    # Game settings
    starting_life: int = 20
    starting_hand_size: int = 7

    # Tuning
    max_deck_changes_per_cycle: int = 3
    matches_per_cycle: int = 50
    heuristic_confidence_threshold: float = 0.85

    # Logging
    log_level: str = "INFO"

    @property
    def cards_db_path(self) -> Path:
        return self.data_dir / "cards" / "cards.db"

    @property
    def decks_dir(self) -> Path:
        return self.config_dir / "decks"

    @property
    def prompts_dir(self) -> Path:
        return self.config_dir / "prompts"


settings = Settings()
