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

**Results (2000 queries, 20000-name gallery, identical sample per model).** MRR by
namespace:

| namespace | MiniLM | BioLORD | MedCPT | SapBERT |
|---|---|---|---|---|
| overall | 0.545 | 0.580 | 0.611 | **0.736** |
| HGNC (genes) | 0.19 | 0.22 | 0.26 | **0.47** |
| PR (proteins) | 0.14 | 0.16 | 0.32 | **0.46** |
| MONDO (disease) | 0.41 | 0.48 | 0.46 | **0.68** |
| CHEBI (chemicals) | 0.42 | 0.47 | 0.45 | **0.62** |
| HP (phenotype) | 0.67 | 0.84 | 0.75 | **0.89** |
| GO (gene function) | 0.70 | 0.79 | 0.79 | **0.87** |
| UBERON (anatomy) | 0.70 | 0.76 | 0.74 | **0.85** |
| OBA (attributes) | 0.86 | 0.89 | 0.91 | **0.97** |
| UPHENO | **0.92** | 0.80 | 0.89 | 0.91 |

MiniLM is a general-purpose model and the floor; it fails on gene and protein symbols,
where a synonym is an alias like `PARK2` with no meaning on its surface. SapBERT —
trained directly on concept synonymy from the UMLS medical vocabulary — wins every
namespace but one and closes the gene/protein gap that a general model cannot. The
other two biomedical models beat the baseline only modestly: the training objective,
not being biomedical as such, is what separates them.

**Pooling.** SapBERT and MedCPT are PubMedBERT-family encoders trained on the `[CLS]`
token; `build_model()` gives them CLS pooling rather than the mean pooling
sentence-transformers applies by default, so they are not understated. BioLORD and
MiniLM are native sentence-transformers and bring their own pooling.

**Caveat on MedCPT.** MedCPT is an asymmetric query-and-document retriever; this test
runs its query encoder on both sides, which is not its intended use, so its number is
a floor. It does not change the ranking — SapBERT is the model.
