"""Run the Page Core API: ``python -m page_core.api --vault PATH``.

Every request needs the API token. It is read from ``PAGE_API_TOKEN`` (for a
process that launches the API and the desktop app together) or generated for
this launch and printed, so the user can paste it into the desktop app. It is
never accepted as a command-line argument, which other users can see in the
process list, and never written into the vault, which may be synced.
"""

import argparse
import logging
import os
from pathlib import Path

import uvicorn

from page_core.api.app import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    Settings,
    create_app,
    new_api_token,
    parse_sync_interval,
    validate_api_token,
)
from page_core.embeddings.encoder import DEFAULT_MODEL
from page_core.vault import FileSystemVault, VaultNotFoundError


def _sync_interval(value: str) -> float:
    try:
        return parse_sync_interval(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m page_core.api")
    parser.add_argument(
        "--vault",
        type=Path,
        default=os.environ.get("PAGE_VAULT_PATH"),
        help="vault folder (default: $PAGE_VAULT_PATH)",
    )
    parser.add_argument(
        "--init",
        metavar="NAME",
        help="create a vault with this name at --vault first if there is none",
    )
    parser.add_argument(
        "--model",
        default=os.environ.get("PAGE_EMBEDDING_MODEL", DEFAULT_MODEL),
        help=f"Sentence Transformers model (default: {DEFAULT_MODEL})",
    )
    parser.add_argument(
        "--sync-interval",
        type=_sync_interval,
        default=os.environ.get("PAGE_INDEX_SYNC_INTERVAL", "30"),
        help="seconds between index syncs; 0 syncs only at startup and on request",
    )
    parser.add_argument("--port", type=int, default=int(os.environ.get("PAGE_API_PORT", DEFAULT_PORT)))
    args = parser.parse_args()
    if args.vault is None:
        parser.error("--vault or PAGE_VAULT_PATH is required")

    vault_path = args.vault.expanduser()
    try:
        FileSystemVault.open(vault_path)
    except VaultNotFoundError:
        if not args.init:
            parser.error(f"no Page vault at {vault_path}; pass --init NAME to create one")
        FileSystemVault.create(vault_path, args.init)

    supplied = os.environ.get("PAGE_API_TOKEN")
    try:
        token = validate_api_token(supplied) if supplied else new_api_token()
    except ValueError as exc:
        parser.error(f"PAGE_API_TOKEN: {exc}")

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    settings = Settings(vault_path, args.model, args.sync_interval, api_token=token)
    if not supplied:
        print(f"Page Core API token for this launch (paste it into Page):\n\n    {token}\n", flush=True)
    uvicorn.run(create_app(settings), host=DEFAULT_HOST, port=args.port)


if __name__ == "__main__":
    main()
