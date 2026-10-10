"""Explicitly launched, authenticated loopback development bridge.

    PYTHONPATH=packages/core/src python -m page_core.ingestion.server /path/to/vault

The vault must already exist. A random session token is printed on startup.
Semantic search is disabled unless --development-search is supplied.
"""

import argparse
import hmac
import json
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from page_core.vault import FileSystemVault, NoteNotFoundError, NoteTooLargeError, VaultError
from .index import IngestionIndex

ALLOWED_ORIGINS = frozenset({"http://localhost:1420", "http://127.0.0.1:1420",
                             "tauri://localhost", "http://tauri.localhost", "https://tauri.localhost"})


def create_server(index: IngestionIndex, *, token: str, port: int = 8765,
                  development_search: bool = False) -> ThreadingHTTPServer:
    if len(token) < 24:
        raise ValueError("session token must have at least 24 characters")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass  # Never log authorization tokens or note/query contents.

        def reply(self, code, payload):
            data = json.dumps(payload).encode()
            self.send_response(code)
            origin = self.headers.get("Origin")
            if origin in ALLOWED_ORIGINS:
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Vary", "Origin")
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def authorized(self):
            if self.headers.get("Origin") not in (None, *ALLOWED_ORIGINS):
                self.reply(403, {"error": "origin not allowed"})
                return False
            supplied = self.headers.get("Authorization", "")
            if not hmac.compare_digest(supplied.encode(), f"Bearer {token}".encode()):
                self.reply(401, {"error": "invalid session token"})
                return False
            return True

        def do_OPTIONS(self):
            if self.headers.get("Origin") not in ALLOWED_ORIGINS:
                self.reply(403, {"error": "origin not allowed"})
                return
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", self.headers["Origin"])
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
            self.send_header("Vary", "Origin")
            self.end_headers()

        def do_GET(self):
            if self.authorized():
                if self.path == "/api/index/status":
                    self.reply(200, {"vault": index.vault.vault.name, **index.status()})
                elif self.path == "/api/context":
                    self.reply(200, {"notes": index.list_context()})
                elif self.path.startswith("/api/context/"):
                    identifier = self.path.removeprefix("/api/context/")
                    try:
                        self.reply(200, {"note": index.read_context(identifier)})
                    except (KeyError, NoteNotFoundError, FileNotFoundError):
                        self.reply(404, {"error": "note not found; index vault changes"})
                    except NoteTooLargeError:
                        self.reply(413, {"error": "note too large"})
                    except (OSError, VaultError):
                        self.reply(422, {"error": "note source is unavailable or unreadable"})
                    except ValueError:
                        self.reply(400, {"error": "invalid note ID"})
                    except Exception:
                        self.reply(500, {"error": "could not read note"})
                else:
                    self.reply(404, {"error": "not found"})

        def do_POST(self):
            if not self.authorized():
                return
            if self.path in ("/api/index", "/api/index/rebuild"):
                started = index.start(rebuild=self.path.endswith("/rebuild"))
                self.reply(202 if started else 409, index.status())
            elif self.path == "/api/dev/search" and development_search:
                try:
                    size = int(self.headers.get("Content-Length", "0"))
                    if not 0 < size <= 8192:
                        raise ValueError("invalid body size")
                    body = json.loads(self.rfile.read(size))
                    query = body["query"]
                    limit = body.get("limit", 10)
                    if not isinstance(query, str) or type(limit) is not int:
                        raise ValueError("invalid query or limit")
                    self.reply(200, {"results": index.search(query, limit=limit)})
                except (ValueError, KeyError, TypeError) as exc:
                    self.reply(400, {"error": str(exc)})
                except Exception:
                    self.reply(500, {"error": "search failed; inspect local index status"})
            else:
                self.reply(404, {"error": "not found"})

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("vault", type=Path)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--development-search", action="store_true")
    args = parser.parse_args()
    index = IngestionIndex(FileSystemVault.open(args.vault))
    token = secrets.token_urlsafe(32)
    server = create_server(index, token=token, port=args.port,
                           development_search=args.development_search)
    print(f"Core bridge: http://127.0.0.1:{server.server_port}\nSession token: {token}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        index.wait()


if __name__ == "__main__":
    main()
