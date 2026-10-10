"""Reproducible real MiniLM indexing and end-to-end query benchmark.

PYTHONPATH=packages/core/src .venv/bin/python benchmarks/ingestion.py --notes 100
"""

import argparse
import json
from importlib.metadata import version
import platform
import statistics
import tempfile
import time
from pathlib import Path, PurePosixPath

_import_start = time.perf_counter()
from page_core.ingestion.embedding import MiniLM
from page_core.ingestion.index import IngestionIndex
from page_core.vault import FileSystemVault
_runtime_import_seconds = time.perf_counter() - _import_start


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--notes", type=int, default=100)
    parser.add_argument("--queries", type=int, default=30)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.notes < 1 or args.queries < 1:
        parser.error("notes and queries must be positive")
    with tempfile.TemporaryDirectory() as directory:
        vault = FileSystemVault.create(Path(directory) / "vault", "Benchmark")
        for i in range(args.notes):
            vault.create_note(PurePosixPath(f"note-{i}.md"),
                f"# Research {i}\n\n" + f"Experiment {i} measures semantic retrieval, local Markdown storage, and vector indexing. " * 30
                + f"\n\n## Results {i}\n\nPersistent indexing reuses embeddings after edits and preserves source provenance.\n")
        model = MiniLM()
        start = time.perf_counter()
        _ = model.tokenizer
        model.encode(["warmup"])
        load = time.perf_counter() - start
        index = IngestionIndex(vault, model)
        start = time.perf_counter()
        indexed = index.update()
        full = time.perf_counter() - start
        start = time.perf_counter()
        unchanged = index.update()
        incremental = time.perf_counter() - start
        note = vault.read_note(PurePosixPath("note-0.md"))
        vault.update_note(note, note.content + "\nA new finding improves retrieval accuracy.\n")
        start = time.perf_counter()
        edited = index.update()
        edit_time = time.perf_counter() - start
        index.search("semantic retrieval")
        times = []
        for i in range(args.queries):
            start = time.perf_counter()
            index.search(f"What are the results of experiment {i % args.notes}?")
            times.append((time.perf_counter() - start) * 1000)
        times.sort()
        report = {"platform": platform.platform(), "machine": platform.machine(),
            "python": platform.python_version(), "model": model.key, "device": "cpu",
            "cpu_threads": 1, "corpus": "synthetic Markdown research notes",
            "versions": {name: version(name) for name in ("numpy", "faiss-cpu", "sentence-transformers", "torch", "transformers")},
            "notes": args.notes, "queries": args.queries,
            "runtime_import_seconds": _runtime_import_seconds, "model_load_seconds": load,
            "index_seconds": full, "unchanged_scan_seconds": incremental,
            "single_edit_seconds": edit_time, "query_p50_ms": statistics.median(times),
            "query_p95_ms": times[min(len(times) - 1, int(len(times) * .95))],
            "indexed": indexed, "unchanged": unchanged, "edited": edited,
            "sqlite_bytes": index.database.stat().st_size, "faiss_bytes": index.artifact.stat().st_size}
        output = json.dumps(report, indent=2) + "\n"
        print(output)
        if args.output:
            args.output.write_text(output)


if __name__ == "__main__":
    main()
