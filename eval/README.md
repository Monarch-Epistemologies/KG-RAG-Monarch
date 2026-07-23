# Eval — KG-RAG-Monarch

The shared gold format and its reasoning live in
[`KG-RAG-EDS/eval/README.md`](../../KG-RAG-EDS/eval/README.md). This file covers the
instruments specific to this repo, which run against the extracted subgraph (`data/`).

## Synonym retrieval — picking the embedding model

`bin/eval_synonym_retrieval.py`. This measures how good a given embedding model is at
placing biomedical terms sensibly, which is what decides whether text-embedding
retrieval — embedding node text into vectors and finding context by nearest-neighbour
search — will work at all.

**The idea.** Each node records its own synonyms in a field: "myocardial infarction"
also lists "heart attack". That is a free answer key — the graph is telling us those
two phrases mean the same thing. So we hand the model one held-out synonym, ask which
node's name is nearest by cosine, and check whether it lands on the right node. Do that
a couple thousand times and the score says how well the model understands this
vocabulary.

The gallery it retrieves against holds node **names only**, so the queried synonym is
never in the text being matched. A hit therefore requires the model to place "heart
attack" near "myocardial infarction" on meaning, not on shared words — exactly the
biomedical semantic proximity a domain-trained model should do better than a general
one.

**Why not reuse the EDS gold.** That gold is built for graph-edge traversal: a question
like "symptoms of EDS" has hundreds of phenotype answers reached by walking edges. No
nearest-neighbour search over node text surfaces hundreds of phenotypes from the word
"symptoms", so scoring text-embedding retrieval against it reads near-zero for every
model and tells us nothing about which model is better. Synonym retrieval is
self-supervised from the graph — the answer is the source node id, derived, never
hand-labeled — and separates good models from weak ones sharply.

**Reproducibility.** Sampling is seeded, so every model sees the identical gallery and
query set and the scores are directly comparable. The sampled queries are written to
`eval/synonym_queries.jsonl` (query text, target id, namespace) for inspection.

**Usage.**

    venv/bin/python3 bin/eval_synonym_retrieval.py [model] [n_queries] [gallery_size]

Defaults: `all-MiniLM-L6-v2`, 2000 queries, 20000-node gallery.

**Baseline (MiniLM, a general-purpose model).** Overall MRR 0.545, recall@1 0.50,
recall@10 0.62. The breakdown by namespace is the useful part: strong on descriptive
vocabulary (UPHENO 0.92, OBA 0.86, GO 0.70, HP 0.67, UBERON 0.70), weak on gene and
protein symbols (HGNC 0.19, PR 0.14), where a synonym is an alias like `PARK2` with no
meaning on its surface to match. That gene/protein gap is where a biomedically-trained
model is expected to help — the comparison this instrument is built to run, not one the
baseline settles.
