"""Configuration package. See `settings.py` for the precedence rules."""

from app.config.settings import Settings, get_settings

__all__ = ["Settings", "get_settings"]
