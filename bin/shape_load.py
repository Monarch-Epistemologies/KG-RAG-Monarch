#!/usr/bin/env python3
"""Load the full Monarch KGX dump into a local DuckDB for subgraph-shape queries.

Only the columns the shape questions need. Structure: edge endpoints, predicate,
node id, name, category. Provenance: species, evidence level and knowledge source,
which are the axes a relevance-based pare-back argues over.
"""

import duckdb

import shape_common as sc

sc.DB.parent.mkdir(parents=True, exist_ok=True)
con = duckdb.connect(str(sc.DB))

con.execute(f"""
    CREATE OR REPLACE TABLE nodes AS
    SELECT id, name, category, deprecated, in_taxon, in_taxon_label,
           length(coalesce(description, '')) AS desc_len,
           length(coalesce(synonym, '')) AS syn_len
    FROM read_csv('{sc.NODES_TSV}', {sc.READ_OPTS})
""")

con.execute(f"""
    CREATE OR REPLACE TABLE edges AS
    SELECT subject, object, predicate, knowledge_level, agent_type,
           primary_knowledge_source
    FROM read_csv('{sc.EDGES_TSV}', {sc.READ_OPTS})
""")

print(f"{con.execute('SELECT count(*) FROM nodes').fetchone()[0]:,} nodes")
print(f"{con.execute('SELECT count(*) FROM edges').fetchone()[0]:,} edges")
