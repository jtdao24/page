"""Private MiniLM pipe worker. No FAISS is imported into this process."""

import base64
import contextlib
import json
import sys

from .embedding import MODEL_NAME, MODEL_REVISION


def main():
    model = None
    for line in sys.stdin:
        try:
            message = json.loads(line)
            with contextlib.redirect_stdout(sys.stderr):
                if model is None:
                    import torch
                    from sentence_transformers import SentenceTransformer

                    torch.set_num_threads(1)
                    model = SentenceTransformer(MODEL_NAME, revision=MODEL_REVISION, device="cpu")
                if message["operation"] == "tokenize":
                    response = {"tokens": model.tokenizer.encode(message["text"],
                        add_special_tokens=message["special"], verbose=False)}
                elif message["operation"] == "embed":
                    vectors = model.encode(message["texts"], batch_size=32,
                        normalize_embeddings=True, convert_to_numpy=True,
                        show_progress_bar=False).astype("<f4")
                    response = {"vectors": base64.b64encode(vectors.tobytes()).decode("ascii")}
                else:
                    raise ValueError("unknown model worker operation")
        except Exception as exc:
            response = {"error": f"{type(exc).__name__}: {exc}"}
        sys.stdout.write(json.dumps(response) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
