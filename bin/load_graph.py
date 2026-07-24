#!/usr/bin/env python3
"""Load the extracted subgraph into a queryable, indexed store (build seq: crawler).

The graph-edge traversal crawler walks edges from an anchor node. Reading the 4.1M
edges as a read_csv view re-scans the whole TSV on every hop, and the crawler hits
it many times (once per traversal, plus once per candidate in disambiguation, times
180 gold questions). So we load it once into data/graph.duckdb and index the edge
endpoints, turning each hop into an index lookup instead of a full scan.

Lean on purpose: only the columns the crawler needs. The vectors stay in the
separate embeddings.duckdb; this DB is the graph, not the embeddings.

  nodes(id, category, name)          — 299,950; name is the display label
  edges(subject, object, predicate)  — 4,097,434

Run: load_graph.py   (rebuilds data/graph.duckdb from data/{nodes,edges}.tsv)
"""

import duckdb

import shape_common as sc

NODES_TSV = sc.PROJECT_HOME / "data" / "nodes.tsv"
EDGES_TSV = sc.PROJECT_HOME / "data" / "edges.tsv"
DB = sc.PROJECT_HOME / "data" / "graph.duckdb"

EXPECT_NODES = 299_950
EXPECT_EDGES = 4_097_434


def main():
    if DB.exists():
        DB.unlink()  # rebuild clean; the file is derived, never hand-edited
    con = duckdb.connect(str(DB))

    con.execute(f"""
        CREATE TABLE nodes AS
        SELECT id, category, name
        FROM read_csv('{NODES_TSV}', {sc.READ_OPTS})
    """)
    con.execute(f"""
        CREATE TABLE edges AS
        SELECT subject, object, predicate
        FROM read_csv('{EDGES_TSV}', {sc.READ_OPTS})
    """)

    # The hot path is "edges touching node X"; index both endpoints. Predicate is
    # filtered alongside but the endpoint index already cuts 4.1M to a handful.
    con.execute("CREATE INDEX idx_edges_subject ON edges(subject)")
    con.execute("CREATE INDEX idx_edges_object ON edges(object)")
    con.execute("CREATE UNIQUE INDEX idx_nodes_id ON nodes(id)")

    n_nodes = con.execute("SELECT count(*) FROM nodes").fetchone()[0]
    n_edges = con.execute("SELECT count(*) FROM edges").fetchone()[0]
    assert n_nodes == EXPECT_NODES, f"nodes {n_nodes} != {EXPECT_NODES}"
    assert n_edges == EXPECT_EDGES, f"edges {n_edges} != {EXPECT_EDGES}"
    con.close()
    print(f"{DB.relative_to(sc.PROJECT_HOME)}: {n_nodes} nodes, {n_edges} edges, indexed")


if __name__ == "__main__":
    main()
