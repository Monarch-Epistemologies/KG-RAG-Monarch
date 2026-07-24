#!/usr/bin/env python3
"""Measure this machine's embedding throughput on real corpus text.

Runtime, not memory, is the likely binding constraint on a native-Mac v2, and it has
never been measured — v1's 833 documents finished before the question arose. This
samples the two built corpora (data/node_text.tsv, data/triple_text.tsv from
build_text.py), embeds them into vectors on MPS, and reports documents per second plus
what a full run would cost.

Reading the built corpora, not re-deriving them, means the rate is measured on exactly
the text that will be embedded. Node text is much longer than triple text, so the two
do not embed at the same rate and cannot share one figure.

    embed_throughput.py [model] [sample_size]
"""

import sys
import time

import duckdb

import shape_common as sc

MODEL = sys.argv[1] if len(sys.argv) > 1 else "all-MiniLM-L6-v2"
SAMPLE = int(sys.argv[2]) if len(sys.argv) > 2 else 20_000
BATCH = 64

NODE_TEXT = sc.PROJECT_HOME / "data" / "node_text.tsv"
TRIPLE_TEXT = sc.PROJECT_HOME / "data" / "triple_text.tsv"
READ_OPTS = "delim='\t', header=true"

con = duckdb.connect()


def sample_texts(path):
    full = con.execute(
        f"SELECT count(*) FROM read_csv('{path}', {READ_OPTS})"
    ).fetchone()[0]
    texts = [
        r[0]
        for r in con.execute(
            f"SELECT text FROM read_csv('{path}', {READ_OPTS}) "
            f"WHERE text IS NOT NULL USING SAMPLE {SAMPLE} ROWS (reservoir, 7)"
        ).fetchall()
    ]
    return texts, full


node_sample, FULL_NODES = sample_texts(NODE_TEXT)
triple_sample, FULL_TRIPLES = sample_texts(TRIPLE_TEXT)

from sentence_transformers import SentenceTransformer  # noqa: E402  (after the slow query)

model = SentenceTransformer(MODEL, device="mps")
dim = model.get_sentence_embedding_dimension()
print(f"{MODEL}, {dim} dimensions, batch {BATCH}, MPS\n")

for label, texts, full in [
    ("node text", node_sample, FULL_NODES),
    ("triple text", triple_sample, FULL_TRIPLES),
]:
    chars = sum(len(t) for t in texts) / len(texts)
    model.encode(texts[:BATCH], batch_size=BATCH)  # warm up kernels and caches
    start = time.perf_counter()
    model.encode(texts, batch_size=BATCH, show_progress_bar=False)
    elapsed = time.perf_counter() - start

    rate = len(texts) / elapsed
    hours = full / rate / 3600
    gib_f32 = full * dim * 4 / 1024**3
    print(
        f"{label:12} {len(texts):>7,} docs  {chars:>6.0f} chars avg  "
        f"{elapsed:>6.1f}s  {rate:>8,.0f} docs/s"
    )
    print(
        f"{'':12} full corpus {full:>9,} docs -> {hours:>5.2f} h, "
        f"{gib_f32:.1f} GiB as float32\n"
    )
