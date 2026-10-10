"""HTTP API for Page Core (requires the ``api`` extra)."""

from page_core.api.app import DEFAULT_HOST, DEFAULT_PORT, Settings, create_app

__all__ = ["DEFAULT_HOST", "DEFAULT_PORT", "Settings", "create_app"]
