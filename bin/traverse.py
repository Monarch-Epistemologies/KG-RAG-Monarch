#!/usr/bin/env python3
"""One-hop graph traversal from an anchor node (build seq: crawler, step 4).

Ported from KG-RAG-EDS/bin/project_2_traverse.py to the v2 substrate: the graph
lives in the indexed data/graph.duckdb (not the small eds.duckdb), and a node's
display label is its `name` column (not `text`).

Given an anchor id and a predicate, collect the facts one edge away. This is the
graph-native retrieval step — no embeddings, just an indexed SQL lookup over edges.

Direction is handled generally: the anchor may be the subject OR the object of its
edges (a disease is the subject of has_phenotype but the object of
gene_associated_with_condition), so we match edges with the anchor on either side
and return whichever endpoint is not the anchor. `dir` ('out' = anchor is subject,
'in' = anchor is object) is reported so symmetric predicates that over-return
(e.g. subclass_of both ways) are at least visible.

LEFT JOIN, not inner: 74 nodes carry no text and some carry no name, but they are
still real graph neighbours — an inner join would silently drop those facts, so we
keep them with a null name rather than lose the edge.

Run: traverse.py <anchor_id> <predicate>, or no args for the smoke tests.
"""

import sys

import duckdb

import shape_common as sc

DB = sc.PROJECT_HOME / "data" / "graph.duckdb"

# (anchor_id, predicate) smoke tests: subject-side, object-side, symmetric.
TEST_CASES = [
    ("MONDO:0007947", "biolink:has_phenotype"),  # Marfan -> phenotypes (out)
    ("MONDO:0007947", "biolink:causes"),  # gene/variant -> Marfan (in)
    ("MONDO:0007947", "biolink:subclass_of"),  # disease <-> disease (both)
]


def traverse(con, anchor_id, predicate):
    """Return facts one hop away as (other_id, category, name, dir).

    Matches edges with the anchor on either side; returns the *other* endpoint.
    dir is 'out' when the anchor is the subject, 'in' when it is the object.
    """
    return con.execute(
        """
        SELECT
          CASE WHEN e.subject = $anchor THEN e.object ELSE e.subject END AS other_id,
          n.category,
          n.name,
          CASE WHEN e.subject = $anchor THEN 'out' ELSE 'in' END AS dir
        FROM edges e
        LEFT JOIN nodes n
          ON n.id = CASE WHEN e.subject = $anchor THEN e.object ELSE e.subject END
        WHERE e.predicate = $pred
          AND (e.subject = $anchor OR e.object = $anchor)
        """,
        {"anchor": anchor_id, "pred": predicate},
    ).fetchall()


def main():
    con = duckdb.connect(str(DB), read_only=True)

    if len(sys.argv) > 2:
        cases = [(sys.argv[1], sys.argv[2])]
    else:
        cases = TEST_CASES

    for anchor_id, predicate in cases:
        rows = traverse(con, anchor_id, predicate)
        print(f"\n{anchor_id}  --{predicate.replace('biolink:', '')}-->  ({len(rows)} facts)")
        for other_id, category, name, direction in rows[:8]:
            cat = (category or "").replace("biolink:", "")
            print(f"  [{direction}] {cat:22} {other_id:16} {name or '(no name)'}")
        if len(rows) > 8:
            print(f"  ... and {len(rows) - 8} more")


if __name__ == "__main__":
    main()
