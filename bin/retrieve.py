#!/usr/bin/env python3
"""Retrieve nodes (or triples) by cosine similarity to a question (build seq #3).

The "retrieve" half of text-embedding retrieval: embed the question with the same
model that embedded the corpus, then rank the stored vectors by
array_cosine_similarity. The query model MUST match the corpus's model — vectors from
different models live in different spaces and are not comparable — so the default is
SapBERT, which built data/embeddings.duckdb.

    retrieve.py "what genes cause cystic fibrosis?" [-k 10] [--corpus node|triple]
"""

import argparse

import duckdb

import shape_common as sc
from embed_models import build_model

DEFAULT_MODEL = "cambridgeltl/SapBERT-from-PubMedBERT-fulltext"
DB = sc.PROJECT_HOME / "data" / "embeddings.duckdb"

# corpus -> (table, key columns carried beside the vector)
TABLES = {
    "node": ("node_vectors", ["id", "category"]),
    "triple": ("triple_vectors", ["subject", "predicate", "object"]),
}


def main():
    ap = argparse.ArgumentParser(
        description="Cosine retrieval over the embedded corpus."
    )
    ap.add_argument("question", help="natural-language query")
    ap.add_argument("-k", type=int, default=10, help="how many hits to return")
    ap.add_argument("--corpus", choices=list(TABLES), default="node")
    ap.add_argument(
        "--model", default=DEFAULT_MODEL, help="must match the corpus's model"
    )
    # cpu is the default: one query is instant either way, and it avoids the GPU.
    ap.add_argument("--device", default="cpu")
    args = ap.parse_args()

    table, keys = TABLES[args.corpus]
    model = build_model(args.model, device=args.device)
    dim = model.get_sentence_embedding_dimension()
    qvec = model.encode([args.question], convert_to_numpy=True)[0].tolist()

    con = duckdb.connect(str(DB), read_only=True)
    rows = con.execute(
        f"""
        SELECT {", ".join(keys)}, text,
               array_cosine_similarity(embedding, ?::FLOAT[{dim}]) AS sim
        FROM {table} ORDER BY sim DESC LIMIT ?
        """,
        [qvec, args.k],
    ).fetchall()

    print(f"Q: {args.question}\n")
    for row in rows:
        *key_vals, text, sim = row
        label = " ".join(str(k).replace("biolink:", "") for k in key_vals)
        print(f"  {sim:.3f}  {label}")
        print(f"         {text[:100]}")


if __name__ == "__main__":
    main()
