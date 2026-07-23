"""Error classes 5 and 6: corruption in the materialized corpus before embedding.

5. Dropped or dangling references. build_text.py inner-joins edges to nodes, so any
   edge whose endpoint is missing from nodes.tsv silently vanishes, and any duplicate
   node id would double-count. Assert referential integrity, unique ids, and that every
   edge produced exactly one triple (no silent drop).
6. Empty documents. A node with no name/synonym/description becomes an empty string,
   which embeds to a meaningless (or zero) vector. Assert node text is never empty.
"""

import duckdb
from conftest import DATA, require

READ = "delim='\t', header=true"


def _con():
    con = duckdb.connect()
    con.execute(
        f"CREATE VIEW nodes AS SELECT * FROM read_csv('{DATA / 'nodes.tsv'}', {READ})"
    )
    con.execute(
        f"CREATE VIEW edges AS SELECT * FROM read_csv('{DATA / 'edges.tsv'}', {READ})"
    )
    return con


def test_Nodes_WHEN_extracted_SHOULD_have_unique_ids():
    require(DATA / "nodes.tsv")
    con = _con()
    total, distinct = con.execute(
        "SELECT count(*), count(DISTINCT id) FROM nodes"
    ).fetchone()
    assert total == distinct, f"{total - distinct} duplicate node ids"


def test_Edges_WHEN_extracted_SHOULD_reference_only_present_nodes():
    require(DATA / "nodes.tsv", DATA / "edges.tsv")
    con = _con()
    dangling = con.execute("""
        SELECT count(*) FROM edges e
        LEFT JOIN nodes s ON s.id = e.subject
        LEFT JOIN nodes o ON o.id = e.object
        WHERE s.id IS NULL OR o.id IS NULL
    """).fetchone()[0]
    assert dangling == 0, f"{dangling:,} edges reference a node absent from nodes.tsv"


def test_TripleText_WHEN_built_SHOULD_have_one_row_per_named_edge():
    # build_text intentionally drops triples whose endpoint has no name (documented
    # decision: textless nodes stay in the graph but not the text corpus). The
    # invariant is therefore one triple per edge with both endpoints named — any
    # further shortfall would be a silent join drop.
    require(DATA / "nodes.tsv", DATA / "edges.tsv", DATA / "triple_text.tsv")
    con = _con()
    named_edges = con.execute("""
        SELECT count(*) FROM edges e
        JOIN nodes s ON s.id = e.subject
        JOIN nodes o ON o.id = e.object
        WHERE s.name <> '' AND o.name <> ''
    """).fetchone()[0]
    triples = con.execute(
        f"SELECT count(*) FROM read_csv('{DATA / 'triple_text.tsv'}', {READ})"
    ).fetchone()[0]
    assert triples == named_edges, (
        f"triple_text has {triples:,} rows for {named_edges:,} named-endpoint edges"
    )


def test_NodeText_WHEN_built_SHOULD_have_no_empty_documents():
    require(DATA / "node_text.tsv")
    con = duckdb.connect()
    empty = con.execute(
        f"""SELECT count(*) FROM read_csv('{DATA / "node_text.tsv"}', {READ})
            WHERE text IS NULL OR trim(text) = ''"""
    ).fetchone()[0]
    assert empty == 0, f"{empty:,} node_text rows are empty and would embed to noise"
