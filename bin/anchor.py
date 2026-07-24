#!/usr/bin/env python3
"""Anchor step: resolve a question to the graph node it is about (build seq: crawler).

Entity linking — get from a question's words to the node the question is *about* (the
disease), which is where traversal then starts. Ported from
KG-RAG-EDS/bin/project_2_anchor.py to the v2 substrate: the node vectors are SapBERT
(768-dim, CLS) in data/embeddings.duckdb, and SapBERT already measured 0.95 anchor
recall on the gold — this is the crawler's validated front door.

Unlike the predicate step (which uses MiniLM, in its own space), the anchor MUST use
SapBERT: it compares the question against the stored node vectors, so it has to live in
the same space those vectors were built in.

Run with a question as args, or no args for the test spread.
"""

import sys

import duckdb
import numpy as np

import shape_common as sc
from embed_models import build_model

MODEL = "cambridgeltl/SapBERT-from-PubMedBERT-fulltext"  # must match node_vectors
DB = sc.PROJECT_HOME / "data" / "embeddings.duckdb"
DIM = 768
K = 25  # generous: the disease must be in the candidate pool for disambiguation to pick it

TEST_QUESTIONS = [
    "What gene is associated with Marfan syndrome?",
    "What are the symptoms of cystic fibrosis?",
    "What is used to treat Marfan syndrome?",
]


def anchor(con, model, question, k=K):
    """Return the k nearest node candidates as (id, category, text, similarity)."""
    qv = model.encode([question], convert_to_numpy=True)[0].astype(np.float32).tolist()
    return con.execute(
        f"""
        SELECT id, category, text,
               array_cosine_similarity(embedding, ?::FLOAT[{DIM}]) AS sim
        FROM node_vectors
        ORDER BY sim DESC
        LIMIT ?
        """,
        [qv, k],
    ).fetchall()


def main():
    con = duckdb.connect(str(DB), read_only=True)
    model = build_model(MODEL, device="cpu")

    questions = [" ".join(sys.argv[1:])] if len(sys.argv) > 1 else TEST_QUESTIONS
    for question in questions:
        print(f"\nQ: {question}")
        for id_, category, text, sim in anchor(con, model, question, k=5):
            cat = (category or "").replace("biolink:", "")
            print(f"  {sim:.3f}  {cat:20} {id_:16} {text[:50]}")


if __name__ == "__main__":
    main()
