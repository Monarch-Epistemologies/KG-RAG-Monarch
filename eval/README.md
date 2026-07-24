# Eval — KG-RAG-Monarch

The shared gold format and its reasoning live in
[`KG-RAG-EDS/eval/README.md`](../../KG-RAG-EDS/eval/README.md). This file covers the
instruments specific to this repo, which run against the extracted subgraph (`data/`).

## Quality in context — does retrieval surface the facts a question needs?

`bin/eval_build_gold.py` (build the gold) and `bin/eval_score.py` (score against it).
Where synonym retrieval picks the *model*, this measures whether the chosen model,
over a given corpus, actually answers realistic questions.

**The gold.** `config/eval_questions.yaml` defines three question types — a disease's
phenotypes, its causative genes, its recorded treatments (the line's use cases, minus
the inference step; see the config's note on why treatment lookup is not repurposing).
For each, `eval_build_gold.py` samples diseases carrying the relevant predicate,
templates a question, and derives the answer set straight from the graph (the graph is
its own answer key). 180 cases -> `eval/gold_monarch.jsonl`. These are
**traversal-shaped**: the answer is a disease's graph neighbours, not a text-similar
node.

**The score.** `eval_score.py` embeds each question, takes the top-k nearest nodes, and
reports recall of the answer entities, plus anchor recall (did it at least find the
disease the question names).

**Result (k=20), three retrieval methods on the same gold.** Answer recall (node/triple
via `eval_score.py`; graph-edge traversal via `eval_crawl.py`, which has no top-k — a walk
returns every neighbour along the picked predicates):

| type | node | triple | traversal |
|---|---|---|---|
| phenotype | 0.02 | 0.49 | **0.89** |
| gene | 0.05 | 0.70 | 0.60 |
| treatment | 0.00 | 0.52 | **0.88** |
| overall | **0.02** | **0.57** | **0.79** |

Traversal (bin/crawl.py: anchor -> predicate-pick -> disambiguate -> traverse) wins
overall. Its ceiling is entity-linking, not the walk: the gold answers are exactly the
edges it follows, so every point lost is an anchor mispick or predicate miss (overall
anchor accuracy 0.79). Genes are its weak type (0.60, anchor accuracy 0.65); the miss
breakdown (of 60): ~14 near-synonym subtype mispicks (the question names a disease family
generically, the graph splits it into subtypes with different genes, and a sibling
outranks the gold — mostly irreducible ambiguity, only 2/13 siblings share the gold gene),
4 anchor-recall gaps, 3 residual predicate-misses. A fixed classifier bug lived here too:
`expressed_in`'s description contained "gene expression", so the word "gene" mis-routed
"what gene is associated with X" onto expressed_in.

The crawler's one non-obvious lesson: v1's disambiguation (pick the candidate with the
most edges of the picked predicate) does active harm at Monarch scale — a common phenotype
is the object of hundreds of has_phenotype edges, so max-count picks the densest leaf, not
the disease, and overrules a SapBERT anchor that was already right (naive port scored 0.37
overall). The fix is minimal: take the first embedding-ranked candidate that is a disease
and carries >=1 edge of a picked predicate. See doc/substack_draft.md section 5.

Node-text retrieval finds the disease the question is about 95% of the time but almost
never surfaces its phenotypes, genes or treatments — because a phenotype node's text
("Scoliosis") is not similar to "symptoms of X". So text-embedding over nodes answers
"what is X" (entity lookup), not "what are X's neighbours" (the actual question).
Triple-text retrieval, where the fact "X has_phenotype Scoliosis" is itself a
document, clears that baseline by more than 20x (0.57 vs 0.02). The nodes-vs-triples
fork is settled: for these questions the unit embedded must be the fact, not the entity.

Scoring the triple corpus is also where brute-force cosine gives out: the ~12 GB of
triple vectors do not fit in RAM, so `surfaced_triple` streams the table once and keeps
a running top-k per question (one scan for all 180) rather than an `ORDER BY` scan per
question (180 scans, killed after 18 min, I/O bound). See the notebook's "from brute
force to an index" for why a live system needs an ANN index past this point.

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
| overall | 0.542 | 0.560 | 0.592 | **0.716** |
| HGNC (genes) | 0.19 | 0.19 | 0.23 | **0.39** |
| PR (proteins) | 0.09 | 0.14 | 0.26 | **0.42** |
| MONDO (disease) | 0.45 | 0.47 | 0.48 | **0.70** |
| CHEBI (chemicals) | 0.46 | 0.49 | 0.48 | **0.64** |
| HP (phenotype) | 0.76 | 0.88 | 0.79 | **0.93** |
| GO (gene function) | 0.73 | 0.80 | 0.80 | **0.92** |
| UBERON (anatomy) | 0.66 | 0.67 | 0.70 | **0.77** |
| OBA (attributes) | 0.91 | 0.92 | 0.93 | **0.98** |
| UPHENO | 0.93 | 0.80 | 0.91 | **0.93** |

MiniLM is a general-purpose model and the floor; it fails on gene and protein symbols,
where a synonym is an alias like `PARK2` with no meaning on its surface. SapBERT —
trained directly on concept synonymy from the UMLS medical vocabulary — takes the top
score in every namespace (UPHENO now a virtual tie with the general model) and closes
the gene/protein gap that a general model cannot. The other two biomedical models beat
the baseline only modestly: the training objective, not being biomedical as such, is
what separates them.

(These numbers are the deterministic hash-ordered sample; see issue #1. The reservoir
sample they replaced gave slightly higher magnitudes — SapBERT 0.736 overall — but the
identical ranking.)

### Pooling: reading one vector out of a model

This matters enough to be explicit, because getting it wrong silently understates a
model and would corrupt the comparison above.

A model does not emit one vector for a whole text. It splits the text into tokens
(word-pieces) and emits one vector *per token*. But retrieval needs exactly one vector
per node's text — one thing to compare by cosine. So the per-token vectors have to be
squashed down to a single text vector, and there are two ways to do it:

- **CLS pooling.** These models prepend a special token, `[CLS]` (short for
  "classification"), at the front of every input. It is not a real word, so it is free
  to be trained as a summary slot, and through attention it can absorb information from
  every other token. CLS pooling just reads the vector sitting on that slot — the model
  has already done the squashing for you.
- **Mean pooling.** Ignore the summary slot and take the average of the text's
  per-token vectors yourself.

Neither is universally correct. Each pooling is only good if the model was *trained*
with it: a model trained to fill its `[CLS]` slot has a strong CLS vector and a
mediocre average, and vice versa. Read a model the way it was not trained and its
vectors are blurred — it will look worse than it is, for a reason that has nothing to
do with the model's actual quality.

So pooling is **not** a variable in the comparison — there is no CLS-vs-mean bake-off.
Each model has one correct pooling, and the comparison uses only that:

| model | family | pooling |
|---|---|---|
| MiniLM, BioLORD | native sentence-transformers | mean (built in) |
| SapBERT, MedCPT | PubMedBERT-family | CLS |

`bin/embed_models.py` `build_model()` encodes this rule so no model is ever read the
wrong way by accident, and a test asserts it applied CLS where required — which is what
makes the results above trustworthy rather than an artifact of mis-pooling.

**Caveat on MedCPT.** MedCPT is an asymmetric query-and-document retriever; this test
runs its query encoder on both sides, which is not its intended use, so its number is
a floor. It does not change the ranking — SapBERT is the model.
