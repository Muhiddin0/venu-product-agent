"""Application configuration management."""

import json
from pathlib import Path
from typing import List, Optional

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

load_dotenv()


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # OpenAI Configuration
    openai_api_key: str

    # API Configuration
    api_title: str = "AI Product Generator"
    api_version: str = "1.0.0"

    # OpenAI Model Configuration
    openai_model: str = "gpt-4o-mini"
    openai_temperature: float = 0.3
    openai_max_retries: int = 2

    # Models
    gpt3_5_turbo: str = "gpt-3.5-turbo"
    gpt4: str = "gpt-4"
    gpt4o_mini: str = "gpt-4o-mini"

    # Venu API Configuration
    venu_base_url: str = "https://api.venu.uz"
    venu_temp_token: Optional[str] = None
    venu_email: Optional[str] = None
    venu_password: Optional[str] = None

    # Marketplace URLs for image search
    # Can be set via MARKETPLACE_URLS environment variable (comma-separated)
    # Example: MARKETPLACE_URLS=https://venu.uz,https://uzum.uz,https://www.amazon.com
    # Note: Pydantic will automatically parse comma-separated strings into lists
    marketplace_urls: Optional[str] = None

    model_config = SettingsConfigDict(
        env_file=".env", case_sensitive=False, extra="ignore"
    )

    @property
    def get_marketplace_urls(self) -> List[str]:
        """
        Get marketplace URLs as a list.

        Returns:
            List of marketplace URLs
        """
        if self.marketplace_urls:
            # Parse comma-separated string
            if isinstance(self.marketplace_urls, str):
                return [
                    url.strip()
                    for url in self.marketplace_urls.split(",")
                    if url.strip()
                ]
            elif isinstance(self.marketplace_urls, list):
                return self.marketplace_urls

        # Default marketplaces
        return [
            "https://venu.uz",
            "https://uzum.uz",
            "https://www.amazon.com",
        ]


# Global settings instance
settings = Settings()

# Validate required settings
if not settings.openai_api_key:
    raise RuntimeError("OPENAI_API_KEY not found. Please add it to .env file.")


def get_image_config() -> dict:
    """Load image config from config.json."""
    config_path = Path(__file__).parent / "config.json"
    if config_path.exists():
        with open(config_path) as f:
            data = json.load(f)
            return data.get("image", {})
    return {}


def get_not_allowed_sites() -> List[str]:
    """Get list of sites whose images should be filtered out from search results."""
    return get_image_config().get("not_allowed_sites", [])


def load_full_config() -> dict:
    """Load full config from config.json."""
    config_path = Path(__file__).parent / "config.json"
    if config_path.exists():
        with open(config_path) as f:
            return json.load(f)
    return {}


def save_full_config(data: dict) -> None:
    """Save full config to config.json."""
    config_path = Path(__file__).parent / "config.json"
    with open(config_path, "w") as f:
        json.dump(data, f, indent=2)
