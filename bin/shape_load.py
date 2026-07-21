#!/usr/bin/env python3
"""Load the full Monarch KGX dump into a local DuckDB for subgraph-shape queries.

Only the columns the shape questions need — edge endpoints plus predicate, node id
plus name and category. Written once, queried by the other shape_* scripts.
"""

import duckdb

import shape_common as sc

sc.DB.parent.mkdir(parents=True, exist_ok=True)
con = duckdb.connect(str(sc.DB))

con.execute(f"""
    CREATE OR REPLACE TABLE nodes AS
    SELECT id, name, category, deprecated
    FROM read_csv('{sc.NODES_TSV}', {sc.READ_OPTS})
""")

con.execute(f"""
    CREATE OR REPLACE TABLE edges AS
    SELECT subject, object, predicate
    FROM read_csv('{sc.EDGES_TSV}', {sc.READ_OPTS})
""")

print(f"{con.execute('SELECT count(*) FROM nodes').fetchone()[0]:,} nodes")
print(f"{con.execute('SELECT count(*) FROM edges').fetchone()[0]:,} edges")
