"""Run the Page Core API: ``python -m page_core.api --vault PATH``."""

import argparse
import logging
import os
from pathlib import Path

import uvicorn

from page_core.api.app import DEFAULT_HOST, DEFAULT_PORT, Settings, create_app
from page_core.embeddings.encoder import DEFAULT_MODEL
from page_core.vault import FileSystemVault, VaultNotFoundError


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
        type=float,
        default=float(os.environ.get("PAGE_INDEX_SYNC_INTERVAL", "30")),
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

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    settings = Settings(vault_path, args.model, args.sync_interval)
    uvicorn.run(create_app(settings), host=DEFAULT_HOST, port=args.port)


if __name__ == "__main__":
    main()
