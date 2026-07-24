#!/usr/bin/env python3
"""Synonym-retrieval eval: does an embedding place a term's synonym near the term?

This is the discriminator for choosing an embedding model (notebook section 3). Each
node in the subgraph may carry synonyms — a MONDO or HP term's alternate labels. We
query with one held-out synonym and retrieve against a gallery of node *names*, then
score the rank of the true node. The graph is its own answer key: the gold for a
query is simply the id of the node the synonym came from, derived, never labeled.

Name-only gallery text means the synonym is never in the document being matched, so a
hit requires the embedding to place "heart attack" near "myocardial infarction" —
exactly the biomedical semantic proximity a domain-trained model should beat a general
one on. Sampling is seeded, so every model sees the identical gallery and query set and
the scores are comparable.

    eval_synonym_retrieval.py [model] [n_queries] [gallery_size]
"""

import json
import sys

import duckdb
import numpy as np

import shape_common as sc

MODEL = sys.argv[1] if len(sys.argv) > 1 else "all-MiniLM-L6-v2"
N_QUERIES = int(sys.argv[2]) if len(sys.argv) > 2 else 2_000
GALLERY_SIZE = int(sys.argv[3]) if len(sys.argv) > 3 else 20_000
SEED = 7  # fixes the sample so runs across models are comparable
K = [1, 5, 10]  # recall@k cutoffs reported

NODES = sc.PROJECT_HOME / "data" / "nodes.tsv"
QUERIES_OUT = sc.PROJECT_HOME / "eval" / "synonym_queries.jsonl"
READ_OPTS = "delim='\t', header=true"


def parse_synonyms(field):
    """Parse the dump's list-shaped synonym field: [a, 'b, with comma', c].

    Not valid Python (bare unquoted items), so literal_eval fails. Split on top-level
    commas, respecting ' and " quoting, then strip quotes and whitespace.
    """
    if not field or not field.startswith("["):
        return []
    inner = field[1:-1]
    out, buf, quote = [], [], None
    for ch in inner:
        if quote:
            if ch == quote:
                quote = None
            else:
                buf.append(ch)
        elif ch in "'\"":
            quote = ch
        elif ch == ",":
            out.append("".join(buf).strip())
            buf = []
        else:
            buf.append(ch)
    out.append("".join(buf).strip())
    return [s for s in out if s]


con = duckdb.connect()
con.execute(f"""
    CREATE TABLE nodes AS
    SELECT id, split_part(id, ':', 1) AS ns, name, synonym
    FROM read_csv('{NODES}', {READ_OPTS})
    WHERE name IS NOT NULL AND name <> ''
""")

# Gallery: a fixed pseudo-random sample of node names to retrieve against. The query
# targets are unioned in afterwards so every gold answer is reachable.
#
# Deterministic sampling via ORDER BY hash(id || SEED) LIMIT n, NOT USING SAMPLE
# (reservoir): DuckDB's parallel reservoir sample is not byte-identical across
# connections under multithreading (issue #1), which would score each model on a
# different sample and invalidate the comparison. hash-ordering is stable regardless of
# thread count — the same fix eval_build_gold.py uses.
gallery = con.execute(
    f"SELECT id, name FROM nodes ORDER BY hash(id || '{SEED}') LIMIT {GALLERY_SIZE}"
).fetchall()

# Queries: sample nodes that carry a synonym, hold one out. A synonym equal to the
# name after normalizing case and surrounding punctuation is trivial, so skip it — the
# task is only meaningful on synonyms that actually differ in surface form.
candidates = con.execute(f"""
    SELECT id, ns, name, synonym FROM nodes
    WHERE synonym IS NOT NULL AND synonym <> ''
    ORDER BY hash(id || '{SEED}') LIMIT {N_QUERIES * 3}
""").fetchall()

queries = []  # (query_text, target_id, namespace)
for node_id, ns, name, syn_field in candidates:
    name_norm = name.strip().lower()
    for syn in parse_synonyms(syn_field):
        if syn.strip().lower() != name_norm:
            queries.append((syn, node_id, ns))
            break
    if len(queries) >= N_QUERIES:
        break

gallery_ids = [g[0] for g in gallery]
gallery_pos = {gid: i for i, gid in enumerate(gallery_ids)}
# Guarantee every target is in the gallery (add any missing ones).
for _, target_id, _ in queries:
    if target_id not in gallery_pos:
        gallery_pos[target_id] = len(gallery_ids)
        gallery_ids.append(target_id)
id_to_name = dict(con.execute("SELECT id, name FROM nodes").fetchall())
gallery_names = [id_to_name[gid] for gid in gallery_ids]

QUERIES_OUT.parent.mkdir(parents=True, exist_ok=True)
with open(QUERIES_OUT, "w") as fh:
    for q_text, target_id, ns in queries:
        fh.write(json.dumps({"query": q_text, "target": target_id, "ns": ns}) + "\n")

# build_model applies the right pooling per model family (see bin/embed_models.py and
# eval/README.md). Imported late so torch loads after the DuckDB sampling above.
from embed_models import build_model  # noqa: E402

model = build_model(MODEL)
dim = model.get_sentence_embedding_dimension()
print(f"{MODEL}, {dim} dim | {len(queries):,} queries, {len(gallery_ids):,} gallery\n")


def encode(texts):
    v = model.encode(
        texts, batch_size=64, show_progress_bar=False, convert_to_numpy=True
    )
    return v / np.linalg.norm(v, axis=1, keepdims=True)  # unit vectors -> dot = cosine


gallery_vecs = encode(gallery_names)
query_vecs = encode([q[0] for q in queries])

# Rank of each target = how many gallery items score strictly higher than it.
ranks = []
for i, (_, target_id, _) in enumerate(queries):
    sims = query_vecs[i] @ gallery_vecs.T
    target_sim = sims[gallery_pos[target_id]]
    ranks.append(int((sims > target_sim).sum()) + 1)
ranks = np.array(ranks)

print(f"{'metric':10} {'overall':>9}")
print(f"{'MRR':10} {np.mean(1 / ranks):>9.3f}")
for k in K:
    print(f"{'recall@' + str(k):10} {np.mean(ranks <= k):>9.3f}")

print(f"\n{'namespace':12} {'n':>6} {'MRR':>7} {'r@1':>7} {'r@10':>7}")
ns_arr = np.array([q[2] for q in queries])
for ns in sorted(set(ns_arr), key=lambda x: -(ns_arr == x).sum()):
    m = ns_arr == ns
    if m.sum() >= 20:
        print(
            f"{ns:12} {m.sum():>6,} {np.mean(1 / ranks[m]):>7.3f} "
            f"{np.mean(ranks[m] <= 1):>7.3f} {np.mean(ranks[m] <= 10):>7.3f}"
        )
