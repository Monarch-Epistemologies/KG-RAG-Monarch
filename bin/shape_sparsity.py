#!/usr/bin/env python3
"""What the sparse tail of MONDO costs, and whether it carries text worth embedding.

Buckets every disease term by how many neighbours it has, then asks two things per
bucket: what share of the disease-incident edges those terms account for (the cost
of keeping them), and how much node text they carry (the reason to keep them).
"""

import shape_common as sc

BUCKETS = [(1, 1), (2, 4), (5, 9), (10, 19), (20, 49), (50, 99), (100, 10**9)]

con = sc.connect()

con.execute(
    """
    CREATE OR REPLACE TEMP TABLE disease_degree AS
    SELECT n.id, count(e.other) AS deg
    FROM nodes n
    JOIN (
        SELECT subject AS id, object AS other FROM edges
        UNION ALL
        SELECT object AS id, subject AS other FROM edges
    ) e ON e.id = n.id
    WHERE n.id LIKE ? || '%' AND (n.deprecated IS NULL OR n.deprecated = '')
    GROUP BY n.id
""",
    [sc.SEED_PREFIX],
)

# Node text is what a node-level corpus would actually embed: name, synonyms and
# description concatenated, as v1's node_text.py builds it.
con.execute(
    f"""
    CREATE OR REPLACE TEMP TABLE disease_text AS
    SELECT id,
           length(coalesce(name, '')) AS name_len,
           length(coalesce(description, '')) AS desc_len,
           length(coalesce(synonym, '')) AS syn_len
    FROM read_csv('{sc.NODES_TSV}', {sc.READ_OPTS})
    WHERE id LIKE '{sc.SEED_PREFIX}%'
"""
)

total_terms, total_edges = con.execute(
    "SELECT count(*), sum(deg) FROM disease_degree"
).fetchone()
print(f"{total_terms:,} disease terms, {total_edges:,} disease-incident edge ends\n")

print(
    f"{'neighbours':>12} {'terms':>8} {'% terms':>8} {'edge ends':>11} {'% edges':>8}"
    f" {'has desc':>9} {'median desc':>12} {'median syn':>11}"
)
for low, high in BUCKETS:
    row = con.execute(
        """
        SELECT count(*), coalesce(sum(d.deg), 0),
               avg(CASE WHEN t.desc_len > 0 THEN 1.0 ELSE 0.0 END),
               median(t.desc_len), median(t.syn_len)
        FROM disease_degree d JOIN disease_text t ON t.id = d.id
        WHERE d.deg BETWEEN ? AND ?
    """,
        [low, high],
    ).fetchone()
    terms, edges, has_desc, med_desc, med_syn = row
    label = (
        f"{low}" if low == high else (f"{low}+" if high > 10**8 else f"{low}-{high}")
    )
    print(
        f"{label:>12} {terms:>8,} {100 * terms / total_terms:>7.1f}% {edges:>11,}"
        f" {100 * edges / total_edges:>7.1f}% {100 * has_desc:>8.0f}%"
        f" {med_desc:>12,.0f} {med_syn:>11,.0f}"
    )
