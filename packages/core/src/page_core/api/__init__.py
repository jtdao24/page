"""Page Core's local HTTP API. Importing it opens, starts and binds nothing."""

from .app import create_app

__all__ = ["create_app"]
