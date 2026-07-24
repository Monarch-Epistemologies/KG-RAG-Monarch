#!/usr/bin/env python3
"""Per-disease subgraph shape, using v1's seed-and-hop mechanics.

For each configured disease name substring: how many MONDO seeds it matches, how
big the one- and two-hop neighbourhoods are in nodes and edges, and which single
node in the one-hop frontier has the highest degree — the hub that drives hop-2
growth. Produces the eight-disease table in doc/substack_draft.md section 1.
"""

import shape_common as sc

con = sc.connect()
sc.add_degree_table(con)

print(
    f"{'disease':32} {'seeds':>6} {'h1 nodes':>9} {'h1 induc':>9} "
    f"{'h2 nodes':>9} {'h2 induc':>10} {'h2 incid':>10}  top hub in h1"
)
print("-" * 122)

for pattern in sc.config()["diseases"]:
    con.execute(
        """
        CREATE OR REPLACE TEMP TABLE seeds AS
        SELECT id FROM nodes
        WHERE id LIKE ? || '%'
          AND lower(name) LIKE '%' || ? || '%'
          AND (deprecated IS NULL OR deprecated = '')
    """,
        [sc.SEED_PREFIX, pattern],
    )

    con.execute("""
        CREATE OR REPLACE TEMP TABLE h1_edges AS
        SELECT subject, object FROM edges
        WHERE subject IN (SELECT id FROM seeds) OR object IN (SELECT id FROM seeds)
    """)
    con.execute("""
        CREATE OR REPLACE TEMP TABLE h1_nodes AS
        SELECT DISTINCT id FROM (
            SELECT subject AS id FROM h1_edges
            UNION ALL SELECT object FROM h1_edges
            UNION ALL SELECT id FROM seeds
        )
    """)
    con.execute("""
        CREATE OR REPLACE TEMP TABLE h2_edges AS
        SELECT subject, object FROM edges
        WHERE subject IN (SELECT id FROM h1_nodes) OR object IN (SELECT id FROM h1_nodes)
    """)
    con.execute("""
        CREATE OR REPLACE TEMP TABLE h2_nodes AS
        SELECT DISTINCT id FROM (
            SELECT subject AS id FROM h2_edges
            UNION ALL SELECT object FROM h2_edges
            UNION ALL SELECT id FROM h1_nodes
        )
    """)

    count = lambda table: con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]  # noqa: E731

    # Incident counts (above) keep every edge with one end in the frontier; induced
    # counts keep only edges with both ends inside the node set. A triple corpus is
    # the induced set — if both endpoints are documents, the edge between them is a
    # retrievable fact — so the two differ by a lot and are not interchangeable.
    def induced(node_table):
        return con.execute(f"""
            SELECT count(*) FROM edges
            WHERE subject IN (SELECT id FROM {node_table})
              AND object IN (SELECT id FROM {node_table})
        """).fetchone()[0]

    hub = con.execute("""
        SELECT n.name, n.id, d.deg
        FROM h1_nodes h
        JOIN degree d ON d.id = h.id
        JOIN nodes n ON n.id = h.id
        ORDER BY d.deg DESC LIMIT 1
    """).fetchone()
    hub_text = f"{(hub[0] or hub[1])[:34]} ({hub[2]:,})" if hub else "-"

    print(
        f"{pattern:32} {count('seeds'):>6,} {count('h1_nodes'):>9,} "
        f"{induced('h1_nodes'):>9,} {count('h2_nodes'):>9,} "
        f"{induced('h2_nodes'):>10,} {count('h2_edges'):>10,}  {hub_text}"
    )
