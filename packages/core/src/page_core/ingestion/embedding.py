"""One reusable MiniLM worker; native model and FAISS runtimes stay isolated."""

import atexit
import base64
import json
import subprocess
import sys
from functools import lru_cache
from threading import Lock

import numpy as np

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
MODEL_REVISION = "c9745ed1d9f207416be6d2e6f8de32d1f16199bf"
_model_lock = Lock()


class _Tokenizer:
    def __init__(self, worker):
        self.worker = worker

    def encode(self, text, *, add_special_tokens=True, **kwargs):
        return self.worker.request("tokenize", text=text, special=add_special_tokens)["tokens"]


class _Worker:
    """Serialized JSON RPC over private pipes; never unpickle model outputs."""

    max_seq_length = 256

    def __init__(self):
        self.process = subprocess.Popen(
            [sys.executable, "-m", "page_core.ingestion.model_worker"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            text=True, encoding="utf-8", bufsize=1,
        )
        self.lock = Lock()
        self.tokenizer = _Tokenizer(self)
        atexit.register(self.close)

    def request(self, operation, **payload):
        with self.lock:
            if self.process.poll() is not None:
                raise RuntimeError("MiniLM worker exited; retry indexing to reload the model")
            try:
                self.process.stdin.write(json.dumps({"operation": operation, **payload}) + "\n")
                self.process.stdin.flush()
                line = self.process.stdout.readline()
            except OSError as exc:
                raise RuntimeError("MiniLM worker communication failed") from exc
            if not line:
                raise RuntimeError("MiniLM worker exited without a response")
            response = json.loads(line)
            if "error" in response:
                raise RuntimeError(response["error"])
            return response

    def close(self):
        # EOF lets torch/scikit-learn clean up their native resources normally.
        if self.process.stdin and not self.process.stdin.closed:
            self.process.stdin.close()
        if self.process.poll() is None:
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.terminate()
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait()
        for stream in (self.process.stdin, self.process.stdout):
            if stream:
                stream.close()


@lru_cache(maxsize=1)
def _load_worker():
    return _Worker()


class MiniLM:
    key = f"{MODEL_NAME}@{MODEL_REVISION}"
    dimension = 384

    @property
    def model(self):
        with _model_lock:
            worker = _load_worker()
            if worker.process.poll() is not None:
                _load_worker.cache_clear()
                worker = _load_worker()
            return worker

    @property
    def tokenizer(self):
        return self.model.tokenizer

    def encode(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.empty((0, self.dimension), dtype="float32")
        response = self.model.request("embed", texts=texts)
        vector = np.frombuffer(base64.b64decode(response["vectors"], validate=True), dtype="<f4")
        return vector.reshape(len(texts), self.dimension).copy()
