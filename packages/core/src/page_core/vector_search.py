"""Isolated FAISS CPU runtime. Input and output contain vectors, never note text.

PyTorch and FAISS macOS wheels can bundle conflicting OpenMP runtimes. A fresh
local process avoids loading both runtimes into one address space without using
unsafe duplicate-runtime environment overrides.
"""

import json
import sys


def main() -> None:
    import faiss
    import numpy as np
    payload = json.load(sys.stdin)
    vectors = np.asarray(payload['vectors'], dtype='float32')
    query = np.asarray([payload['query']], dtype='float32')
    faiss.omp_set_num_threads(1)
    index = faiss.IndexFlatIP(vectors.shape[1])
    index.add(vectors)
    scores, positions = index.search(query, len(vectors))
    json.dump([scores[0].tolist(), positions[0].tolist()], sys.stdout, allow_nan=False)


if __name__ == '__main__':
    main()
