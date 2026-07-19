# KG-RAG-Monarch

Version 2 of the KG-RAG line. Where [`KG-RAG-EDS`](../KG-RAG-EDS) is the hand-built,
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

_(to be defined — see the design notebook)_
