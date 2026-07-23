#!/usr/bin/env python3
"""Embed a text corpus into vectors in DuckDB (build seq #3).

Runs each document through the chosen model and stores a fixed-size FLOAT[dim] vector
per row, so retrieval is one ORDER BY array_cosine_similarity query. SapBERT is the
default, chosen by the synonym-retrieval eval (see eval/README.md).

Vectors are inserted a chunk at a time through Arrow (a FixedSizeList column, one bulk
INSERT per chunk) rather than row-by-row parameter binding — the latter is ~30x slower
than the encoding it feeds and leaves the GPU idle. Chunking also caps peak memory, so
this handles the node corpus (~300k) or the far larger triple corpus (~4M) alike.

MPS caveat: a sustained MPS run wedged the process in an uninterruptible GPU wait
around 100k documents (twice), apparently from MPS memory building up across chunks.
torch.mps.empty_cache() after each chunk releases it and keeps the run stable. Pass
device 'cpu' to sidestep the GPU entirely — slower, but immune to the hang.

    embed_corpus.py [node|triple] [model] [max_rows] [device]  # max_rows 0=all
"""

import sys

import duckdb
import pyarrow as pa
import torch

import shape_common as sc
from embed_models import build_model

CORPUS = sys.argv[1] if len(sys.argv) > 1 else "node"
MODEL = (
    sys.argv[2]
    if len(sys.argv) > 2
    else "cambridgeltl/SapBERT-from-PubMedBERT-fulltext"
)
MAX_ROWS = int(sys.argv[3]) if len(sys.argv) > 3 else 0
DEVICE = sys.argv[4] if len(sys.argv) > 4 else "mps"
CHUNK = 20_000  # rows per encode+insert chunk
ENCODE_BATCH = 128

# Each corpus: its text file, DuckDB table, and the key columns carried beside the
# vector so a retrieval hit traces back to its node or triple.
SPEC = {
    "node": {
        "file": sc.PROJECT_HOME / "data" / "node_text.tsv",
        "table": "node_vectors",
        "keys": [("id", "VARCHAR"), ("category", "VARCHAR")],
    },
    "triple": {
        "file": sc.PROJECT_HOME / "data" / "triple_text.tsv",
        "table": "triple_vectors",
        "keys": [
            ("subject", "VARCHAR"),
            ("predicate", "VARCHAR"),
            ("object", "VARCHAR"),
        ],
    },
}
if CORPUS not in SPEC:
    raise SystemExit(f"corpus must be one of {list(SPEC)}, got {CORPUS!r}")
spec = SPEC[CORPUS]
key_names = [k for k, _ in spec["keys"]]
DB = sc.PROJECT_HOME / "data" / "embeddings.duckdb"
READ_OPTS = "delim='\t', header=true"

src = duckdb.connect()
limit = f"LIMIT {MAX_ROWS}" if MAX_ROWS else ""
rows = src.execute(
    f"SELECT {', '.join(key_names)}, text "
    f"FROM read_csv('{spec['file']}', {READ_OPTS}) "
    f"WHERE text IS NOT NULL AND text <> '' {limit}"
).fetchall()
print(f"{len(rows):,} documents from {spec['file'].name}", flush=True)

model = build_model(MODEL, device=DEVICE)
dim = model.get_sentence_embedding_dimension()
print(f"embedding with {MODEL} ({dim}-dim) on {DEVICE}, chunk {CHUNK:,}", flush=True)

con = duckdb.connect(str(DB))
key_cols = ", ".join(f"{name} {typ}" for name, typ in spec["keys"])
con.execute(f"""
    CREATE OR REPLACE TABLE {spec["table"]} (
        {key_cols}, text VARCHAR, embedding FLOAT[{dim}]
    )
""")

n_keys = len(spec["keys"])
for start in range(0, len(rows), CHUNK):
    chunk = rows[start : start + CHUNK]
    texts = [r[n_keys] for r in chunk]
    vecs = model.encode(
        texts, batch_size=ENCODE_BATCH, show_progress_bar=False, convert_to_numpy=True
    ).astype("float32")

    columns = {name: [r[i] for r in chunk] for i, name in enumerate(key_names)}
    columns["text"] = texts
    columns["embedding"] = pa.FixedSizeListArray.from_arrays(
        pa.array(vecs.reshape(-1)), dim
    )
    con.register("chunk", pa.table(columns))
    con.execute(
        f"INSERT INTO {spec['table']} "
        f"SELECT {', '.join(key_names)}, text, embedding FROM chunk"
    )
    con.unregister("chunk")
    # Release MPS memory each chunk; without this a long run wedges the GPU.
    if DEVICE == "mps":
        torch.mps.empty_cache()
    print(f"  {min(start + CHUNK, len(rows)):,}/{len(rows):,}", flush=True)

n = con.execute(f"SELECT count(*) FROM {spec['table']}").fetchone()[0]
print(f"{n:,} rows in {spec['table']} -> {DB.relative_to(sc.PROJECT_HOME)}", flush=True)
con.close()
