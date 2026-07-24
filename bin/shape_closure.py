#!/usr/bin/env python3
"""Grow a disease's neighbourhood hop by hop until it stops growing.

Reports the cumulative node and edge counts at each hop, so the growth curve — and
where, if anywhere, it saturates — is visible rather than assumed. Takes a disease
name substring on the command line, defaulting to the first one in the probe config.
"""

import sys

import shape_common as sc

MAX_HOPS = 12

pattern = sys.argv[1] if len(sys.argv) > 1 else sc.config()["diseases"][0]

con = sc.connect()
con.execute(
    """
    CREATE OR REPLACE TEMP TABLE reached AS
    SELECT id FROM nodes
    WHERE id LIKE ? || '%'
      AND lower(name) LIKE '%' || ? || '%'
      AND (deprecated IS NULL OR deprecated = '')
""",
    [sc.SEED_PREFIX, pattern],
)

total_nodes, total_edges = con.execute(
    "SELECT (SELECT count(*) FROM nodes), (SELECT count(*) FROM edges)"
).fetchone()
seeds = con.execute("SELECT count(*) FROM reached").fetchone()[0]
print(f"{pattern!r}: {seeds:,} seeds\n")
print(f"{'hop':>4} {'nodes':>10} {'new':>10} {'edges':>11} {'% of graph nodes':>17}")

previous = 0
for hop in range(1, MAX_HOPS + 1):
    con.execute("""
        CREATE OR REPLACE TEMP TABLE reached_next AS
        SELECT DISTINCT id FROM (
            SELECT id FROM reached
            UNION ALL
            SELECT e.object AS id FROM edges e WHERE e.subject IN (SELECT id FROM reached)
            UNION ALL
            SELECT e.subject AS id FROM edges e WHERE e.object IN (SELECT id FROM reached)
        )
    """)
    con.execute("CREATE OR REPLACE TEMP TABLE reached AS SELECT id FROM reached_next")

    nodes = con.execute("SELECT count(*) FROM reached").fetchone()[0]
    edges = con.execute("""
        SELECT count(*) FROM edges
        WHERE subject IN (SELECT id FROM reached) AND object IN (SELECT id FROM reached)
    """).fetchone()[0]
    print(
        f"{hop:>4} {nodes:>10,} {nodes - previous:>10,} {edges:>11,}"
        f" {100 * nodes / total_nodes:>16.1f}%"
    )
    if nodes == previous:
        print(
            f"\nsaturated at hop {hop - 1}: {nodes:,} nodes, {edges:,} edges "
            f"({100 * edges / total_edges:.1f}% of the graph's edges)"
        )
        break
    previous = nodes
else:
    print(f"\nstill growing at hop {MAX_HOPS}")
