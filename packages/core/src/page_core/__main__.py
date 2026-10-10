from __future__ import annotations

import os

import uvicorn

from page_core.api import DEFAULT_PORT, create_app


def main() -> None:
    port = int(os.environ.get("PAGE_API_PORT", DEFAULT_PORT))
    uvicorn.run(create_app(), host="127.0.0.1", port=port, log_level="info")


if __name__ == "__main__":
    main()
