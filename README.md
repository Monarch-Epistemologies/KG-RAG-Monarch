# KG-RAG-Monarch

Version 2 of the KG-RAG line. Where [`KG-RAG-EDS`](https://github.com/Monarch-Epistemologies/KG-RAG-EDS) is the hand-built,
educational setup — one disease (Ehlers-Danlos), every step done slowly by hand to
build intuition — this repo scales that pipeline **beyond a single seed set toward
the broader Monarch graph**.

It stays **native on the Mac** (Apple Silicon / MPS). The whole point of v2 is to
learn what scaling costs on hardware we already have: bigger seed sets and subgraphs,
real runtime-vs-quality numbers, a possible move to a biomedical embedding model, and
approximate-nearest-neighbor indexing when brute-force cosine stops being enough.

v1 stays pristine as the teaching version.

## Why not Docker / RunPod here

Deliberately deferred to a future **v3**. Docker on Apple Silicon can't reach the
Mac's GPU (no Metal/MPS passthrough in the Linux-VM container), so containerizing
here would *remove* the acceleration that makes patient local runs viable, while
adding VM RAM pressure on a 16GB machine. Docker earns its keep only at the RunPod
boundary — shipping to a real CUDA GPU.

v3 is entered **only when v2's measured numbers show a step the Mac can't do
patiently** — e.g. a large biomedical model re-embedded repeatedly during tuning,
triple-level embedding of the full graph, or a local generation LLM. Evidence first,
container second.

## Direction & design

See [`doc/`](./doc) for the substack design notebook — the running record of *why*
v2 is shaped the way it is. Written first, before the code.

## Build sequence

The design notebook ([`doc/substack_draft.md`](./doc/substack_draft.md)) argues *why*
the subgraph is shaped the way it is; this is *what* runs, in order. Steps read v1's
pinned KGX dump (`../KG-RAG-EDS/data/`) and write derived artifacts into this repo's
gitignored `data/`. Everything runs natively on the Mac; see the notebook for the v3
tripwire that would end that.

Setup: `python3 -m venv venv && venv/bin/pip install -r requirements.txt`.

1. **Extract the subgraph** — `bin/extract_subgraph.py`. Filters the full dump to the
   human-only relevance cut (442,307 nodes, 4,923,997 edges — the method-neutral
   boundary from notebook §1) into `data/nodes.tsv` and `data/edges.tsv`. The dump is
   never edited; this is a regenerable copy, and the run asserts the expected counts.
2. **Build the text corpora** — one document per node (name + synonyms + description)
   and one per triple (subject name + readable predicate + object name). The two are
   the units the nodes-vs-triples fork (notebook §2) chooses between.
3. **Embed** — run each corpus through a sentence-embedding model into vectors in
   DuckDB, and retrieve by cosine. Which model (notebook §3) and nodes-vs-triples are
   decided here against the shared gold set (`eval/`).

Measurement scripts behind the notebook's numbers live alongside these as
`bin/shape_*.py` (config in `config/shape_probe.yaml`); they only measure, and write
nothing.

## Related

- **Line context (Monarch-Epistemologies).** The positioning that spans the whole
  KG-RAG line lives in the org
  [`.github` repo](https://github.com/Monarch-Epistemologies/.github):
  [retrieval_epistemologies](https://github.com/Monarch-Epistemologies/.github/blob/main/docs/retrieval_epistemologies.md)
  — the modes of knowing behind each retrieval architecture; v2 sits in the
  text-embedding mode, at scale.
  [use_cases](https://github.com/Monarch-Epistemologies/.github/blob/main/docs/use_cases.md) and
  [related_work_phenomics_assistant](https://github.com/Monarch-Epistemologies/.github/blob/main/docs/related_work_phenomics_assistant.md)
  round out the line-level docs.
- **v1:** [KG-RAG-EDS](https://github.com/Monarch-Epistemologies/KG-RAG-EDS) — the
  hand-built teaching version this scales from.
