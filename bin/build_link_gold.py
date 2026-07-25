#!/usr/bin/env python3
"""Build a leakage-free link-prediction gold for the network embedding (build seq:
network embed, soft-retrieval track).

The question gold (gold_monarch.jsonl) scores the structural embedding on edges that
already exist — the one task an exact walk always wins. This gold scores the thing the
embedding is actually for: predicting an edge the model has NOT seen. That only means
anything if the edge is genuinely held out, so this does two things together:

  1. sample K disease<->gene and disease<->phenotype edges, writing them as the test set
     eval/gold_link_prediction.jsonl  ({source disease, target, type}).
  2. write data/graph_lp.duckdb — the whole graph with exactly those edges removed — so
     the embedding retrained on it (embed_network.py --graph) has never seen them.

Targets are required to keep at least one other edge after removal, so a held-out target
still gets embedded and is a fair thing to ask the model to rank. Sampling is hash-order
deterministic (same convention as the synonym eval, issue #1).

    build_link_gold.py [-k 500] [--seed 7]
"""

import argparse
import json

import duckdb

import shape_common as sc

GRAPH_DB = sc.PROJECT_HOME / "data" / "graph.duckdb"
LP_DB = sc.PROJECT_HOME / "data" / "graph_lp.duckdb"
GOLD = sc.PROJECT_HOME / "eval" / "gold_link_prediction.jsonl"
DISEASE = "biolink:Disease"
TARGETS = ("biolink:Gene", "biolink:PhenotypicFeature")


def sample_heldout(con, k, seed):
    """K edges with one Disease endpoint and one gene/phenotype endpoint, whose target
    keeps >=2 total edges (so it survives removal and stays embeddable). Deterministic."""
    con.execute("""
        CREATE TEMP TABLE deg AS
        SELECT id, count(*) c FROM (
            SELECT subject AS id FROM edges UNION ALL SELECT object FROM edges
        ) GROUP BY id
    """)
    rows = con.execute(
        f"""
        WITH edge_ends AS (
            SELECT e.subject, e.object, e.predicate,
                   CASE WHEN a.category = '{DISEASE}' THEN e.subject ELSE e.object END AS source,
                   CASE WHEN a.category = '{DISEASE}' THEN e.object  ELSE e.subject END AS target,
                   CASE WHEN a.category = '{DISEASE}' THEN b.category ELSE a.category END AS target_cat
            FROM edges e
            JOIN nodes a ON e.subject = a.id
            JOIN nodes b ON e.object = b.id
            WHERE (a.category = '{DISEASE}' AND b.category IN {TARGETS})
               OR (b.category = '{DISEASE}' AND a.category IN {TARGETS})
        )
        SELECT ee.subject, ee.object, ee.predicate, ee.source, ee.target, ee.target_cat
        FROM edge_ends ee
        JOIN deg ON deg.id = ee.target AND deg.c >= 2
        -- balance the two target types: has_phenotype edges vastly outnumber gene edges,
        -- so take up to k/2 of each rather than a raw sample that would be nearly all
        -- phenotypes. row_number over a hashed order keeps it deterministic.
        QUALIFY row_number() OVER (
            PARTITION BY ee.target_cat
            ORDER BY hash(ee.subject || ee.object || ee.predicate || '{seed}')
        ) <= {k // len(TARGETS)}
        """
    ).fetchall()
    return rows


def main():
    ap = argparse.ArgumentParser(description="Build the link-prediction gold and held-out graph.")
    ap.add_argument("-k", type=int, default=500, help="number of edges to hold out")
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    con = duckdb.connect(str(GRAPH_DB), read_only=True)
    rows = sample_heldout(con, args.k, args.seed)
    if len(rows) < args.k:
        print(f"note: only {len(rows)} eligible edges (< {args.k} requested)")

    # 1. the test set
    with open(GOLD, "w") as fh:
        for subject, obj, predicate, source, target, target_cat in rows:
            kind = "gene" if target_cat == "biolink:Gene" else "phenotype"
            fh.write(json.dumps({
                "source": source, "target": target, "type": kind,
                "subject": subject, "object": obj, "predicate": predicate,
            }) + "\n")

    # 2. the held-out graph: every edge except the sampled triples
    if LP_DB.exists():
        LP_DB.unlink()
    heldout = {(s, o, p) for s, o, p, *_ in rows}
    out = duckdb.connect(str(LP_DB))
    out.execute(f"ATTACH '{GRAPH_DB}' AS g (READ_ONLY)")
    out.execute("CREATE TABLE nodes AS SELECT * FROM g.nodes")
    out.execute("CREATE TABLE edges AS SELECT * FROM g.edges")
    out.executemany(
        "DELETE FROM edges WHERE subject = ? AND object = ? AND predicate = ?",
        list(heldout),
    )
    removed = out.execute("SELECT count(*) FROM g.edges").fetchone()[0] - \
        out.execute("SELECT count(*) FROM edges").fetchone()[0]
    out.close()

    by_type = {}
    for _s, _o, _p, _src, _tgt, tcat in rows:
        by_type[tcat] = by_type.get(tcat, 0) + 1
    print(f"{GOLD.relative_to(sc.PROJECT_HOME)}: {len(rows)} held-out edges {by_type}")
    print(f"{LP_DB.relative_to(sc.PROJECT_HOME)}: graph with {removed} edge rows removed")


if __name__ == "__main__":
    main()
