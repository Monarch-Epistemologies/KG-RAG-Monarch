#!/usr/bin/env python3
"""Build the two candidate text corpora from the extracted subgraph (build seq #2).

Reads this repo's derived subgraph (data/nodes.tsv, data/edges.tsv) and writes one
document per node and one per triple. These are the units the nodes-vs-triples fork
in doc/substack_draft.md section 2 chooses between; both are built so the choice can
be made by measurement rather than argument.

  node_text.tsv   — id, category, text   where text = name. synonyms. description
                    (concat_ws skips missing fields, matching v1's node_text.py)
  triple_text.tsv — subject, predicate, object, text   where text is the subject
                    name, the predicate with its biolink prefix and underscores
                    removed, and the object name: "Marfan syndrome has phenotype
                    Aortic dilatation"
"""

import duckdb

import shape_common as sc

NODES = sc.PROJECT_HOME / "data" / "nodes.tsv"
EDGES = sc.PROJECT_HOME / "data" / "edges.tsv"
OUT_NODE_TEXT = sc.PROJECT_HOME / "data" / "node_text.tsv"
OUT_TRIPLE_TEXT = sc.PROJECT_HOME / "data" / "triple_text.tsv"

# nodes.tsv / edges.tsv were written by DuckDB COPY, so they are clean quoted TSV —
# read them with default quoting, not the quote='' the raw dump needed.
READ_OPTS = "delim='\t', header=true"

con = duckdb.connect()
con.execute(f"CREATE VIEW nodes AS SELECT * FROM read_csv('{NODES}', {READ_OPTS})")
con.execute(f"CREATE VIEW edges AS SELECT * FROM read_csv('{EDGES}', {READ_OPTS})")

con.execute(f"""
    COPY (
        SELECT id, category, concat_ws('. ', name, synonym, description) AS text
        FROM nodes
    ) TO '{OUT_NODE_TEXT}' (FORMAT csv, DELIMITER '\t', HEADER)
""")
n_nodes = con.execute("SELECT count(*) FROM nodes").fetchone()[0]

# The readable predicate is a tuning-adjacent transform, but a mechanical one (strip
# prefix, underscores to spaces), so it stays inline rather than in the config.
con.execute(f"""
    COPY (
        SELECT
            e.subject,
            e.predicate,
            e.object,
            concat_ws(' ',
                s.name,
                replace(replace(e.predicate, 'biolink:', ''), '_', ' '),
                o.name
            ) AS text
        FROM edges e
        JOIN nodes s ON s.id = e.subject
        JOIN nodes o ON o.id = e.object
    ) TO '{OUT_TRIPLE_TEXT}' (FORMAT csv, DELIMITER '\t', HEADER)
""")
n_triples = con.execute("""
    SELECT count(*) FROM edges e
    JOIN nodes s ON s.id = e.subject
    JOIN nodes o ON o.id = e.object
""").fetchone()[0]

# Coverage and length, the two things that decide how much these corpora differ in
# embedding cost and in how much signal each document carries.
node_stats = con.execute("""
    SELECT
        count(*) FILTER (WHERE description IS NOT NULL AND description <> ''),
        avg(length(concat_ws('. ', name, synonym, description)))
    FROM nodes
""").fetchone()

print(
    f"node_text.tsv:   {n_nodes:,} docs, "
    f"{node_stats[0]:,} with a description, {node_stats[1]:.0f} chars avg"
)
print(f"triple_text.tsv: {n_triples:,} docs")
if n_triples < con.execute("SELECT count(*) FROM edges").fetchone()[0]:
    dropped = con.execute("SELECT count(*) FROM edges").fetchone()[0] - n_triples
    print(f"  ({dropped:,} edges dropped: an endpoint missing from nodes.tsv)")
