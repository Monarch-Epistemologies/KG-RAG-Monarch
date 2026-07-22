#!/usr/bin/env python3
"""Measure this machine's embedding throughput on real corpus text.

Runtime, not memory, is the likely binding constraint on a native-Mac v2, and it has
never been measured — v1's 833 documents finished before the question arose. This
samples the two candidate corpora, embeds them into vectors on MPS, and reports
documents per second plus what a full run would cost.

Node text is name, synonyms and description concatenated, as v1's node_text.py builds
it. Triple text is subject name, a readable predicate and object name — much shorter,
so the two corpora do not embed at the same rate and cannot share one figure.

    embed_throughput.py [model] [sample_size]
"""

import sys
import time

import shape_common as sc

MODEL = sys.argv[1] if len(sys.argv) > 1 else "all-MiniLM-L6-v2"
SAMPLE = int(sys.argv[2]) if len(sys.argv) > 2 else 20_000
BATCH = 64

# Corpus sizes from the relevance-first pare-back in doc section 1: the human-only
# graph, which is the method-neutral boundary.
FULL_NODES = 442_307
FULL_TRIPLES = 4_923_997

con = sc.connect()

# Node name/synonym/description are not in the shape DB — only their lengths — so the
# text itself comes from the dump for the sampled ids.
con.execute(f"""
    CREATE OR REPLACE TEMP TABLE node_text AS
    SELECT id, name, concat_ws('. ', name, synonym, description) AS text
    FROM read_csv('{sc.NODES_TSV}', {sc.READ_OPTS})
    WHERE name IS NOT NULL
""")

human = """
    coalesce(s.in_taxon_label, 'Homo sapiens') = 'Homo sapiens'
    AND coalesce(o.in_taxon_label, 'Homo sapiens') = 'Homo sapiens'
"""

node_sample = [
    r[0]
    for r in con.execute(
        f"""
    SELECT t.text FROM node_text t
    WHERE t.id IN (
        SELECT s.id FROM edges e JOIN nodes s ON s.id = e.subject
        JOIN nodes o ON o.id = e.object WHERE {human}
    )
    USING SAMPLE {SAMPLE} ROWS (reservoir, 7)
"""
    ).fetchall()
]

triple_sample = [
    r[0]
    for r in con.execute(
        f"""
    SELECT concat_ws(' ', sn.name, replace(replace(e.predicate, 'biolink:', ''), '_', ' '), on_.name)
    FROM edges e
    JOIN nodes s ON s.id = e.subject
    JOIN nodes o ON o.id = e.object
    JOIN node_text sn ON sn.id = e.subject
    JOIN node_text on_ ON on_.id = e.object
    WHERE {human}
    USING SAMPLE {SAMPLE} ROWS (reservoir, 7)
"""
    ).fetchall()
]

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
