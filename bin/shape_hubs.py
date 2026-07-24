#!/usr/bin/env python3
"""What the hub nodes are, and whether cutting them by predicate shrinks the corpus.

Works on the union of all configured diseases as one subgraph, since that is the
unit a real seed set would be. Lists the highest-degree nodes in the one-hop
frontier and the predicates they attach by, then measures each configured
predicate cut against the two-hop corpus size.
"""

import shape_common as sc

cfg = sc.config()
con = sc.connect()
sc.add_degree_table(con)

con.execute("CREATE OR REPLACE TEMP TABLE pats (p VARCHAR)")
con.executemany("INSERT INTO pats VALUES (?)", [[p] for p in cfg["diseases"]])
con.execute(
    """
    CREATE OR REPLACE TEMP TABLE seeds AS
    SELECT DISTINCT n.id FROM nodes n
    JOIN pats ON lower(n.name) LIKE '%' || pats.p || '%'
    WHERE n.id LIKE ? || '%' AND (n.deprecated IS NULL OR n.deprecated = '')
""",
    [sc.SEED_PREFIX],
)

con.execute("""
    CREATE OR REPLACE TEMP TABLE h1_union AS
    SELECT DISTINCT id FROM (
        SELECT subject AS id FROM edges
        WHERE subject IN (SELECT id FROM seeds) OR object IN (SELECT id FROM seeds)
        UNION ALL
        SELECT object FROM edges
        WHERE subject IN (SELECT id FROM seeds) OR object IN (SELECT id FROM seeds)
    )
""")

n_seeds = con.execute("SELECT count(*) FROM seeds").fetchone()[0]
n_h1 = con.execute("SELECT count(*) FROM h1_union").fetchone()[0]
print(
    f"union of {len(cfg['diseases'])} diseases: {n_seeds:,} seeds, {n_h1:,} h1 nodes\n"
)

print(f"top {cfg['hub_list_size']} hubs in the union h1 frontier:")
for hub_id, name, category, deg in con.execute(
    """
    SELECT h.id, n.name, n.category, d.deg
    FROM h1_union h JOIN degree d ON d.id = h.id JOIN nodes n ON n.id = h.id
    ORDER BY d.deg DESC LIMIT ?
""",
    [cfg["hub_list_size"]],
).fetchall():
    print(
        f"  {deg:>7,}  {hub_id:<16} {(name or '')[:44]:<44} "
        f"{(category or '').replace('biolink:', '')}"
    )

print("\npredicates on edges touching the top 5 hubs:")
for predicate, count in con.execute("""
    WITH top AS (
        SELECT h.id FROM h1_union h JOIN degree d ON d.id = h.id
        ORDER BY d.deg DESC LIMIT 5
    )
    SELECT predicate, count(*) AS c FROM edges
    WHERE subject IN (SELECT id FROM top) OR object IN (SELECT id FROM top)
    GROUP BY 1 ORDER BY c DESC LIMIT 8
""").fetchall():
    print(f"  {count:>8,}  {predicate}")

print(
    f"\n{'predicate cut':44} {'h1 nodes':>8} {'h1 edges':>8} {'h2 nodes':>9} {'h2 edges':>10}"
)
for cut in cfg["predicate_cuts"]:
    dropped = cut["drop"]
    clause = ""
    if dropped:
        clause = " AND predicate NOT IN (" + ",".join(f"'{d}'" for d in dropped) + ")"
    con.execute(f"""
        CREATE OR REPLACE TEMP TABLE kept AS
        SELECT subject, object FROM edges WHERE true{clause}
    """)
    con.execute("""
        CREATE OR REPLACE TEMP TABLE h1e AS
        SELECT subject, object FROM kept
        WHERE subject IN (SELECT id FROM seeds) OR object IN (SELECT id FROM seeds)
    """)
    con.execute("""
        CREATE OR REPLACE TEMP TABLE h1n AS
        SELECT DISTINCT id FROM (
            SELECT subject AS id FROM h1e UNION ALL SELECT object FROM h1e
            UNION ALL SELECT id FROM seeds)
    """)
    con.execute("""
        CREATE OR REPLACE TEMP TABLE h2e AS
        SELECT subject, object FROM kept
        WHERE subject IN (SELECT id FROM h1n) OR object IN (SELECT id FROM h1n)
    """)
    con.execute("""
        CREATE OR REPLACE TEMP TABLE h2n AS
        SELECT DISTINCT id FROM (
            SELECT subject AS id FROM h2e UNION ALL SELECT object FROM h2e
            UNION ALL SELECT id FROM h1n)
    """)
    count = lambda table: con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]  # noqa: E731
    print(
        f"{cut['label']:44} {count('h1n'):>8,} {count('h1e'):>8,} "
        f"{count('h2n'):>9,} {count('h2e'):>10,}"
    )
