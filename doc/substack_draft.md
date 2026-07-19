# KG-RAG-Monarch — design notebook (substack draft)

Running record of *why* v2 is shaped the way it is. Written before the code.
This is an outline — sections are the questions v2 has to answer, in roughly the
order they bite. Prose to follow.

---

## 1. What "beyond EDS" means mechanically

From a single seed set to what? More disease seeds, k-hop expansion from seeds, or
the whole node set. This sizes the corpus, which drives everything downstream.

_(draft here)_

## 2. What we embed — nodes vs. triples

The 1.46M-vs-15.2M fork. The single biggest lever on runtime and on whether the Mac
stays viable.

_(draft here)_

## 3. Which embedding model

Quality through training, not brute-force size: general vs. biomedical
(MedCPT / BioLORD / SapBERT). The quality/runtime tables as the evidence.

_(draft here)_

## 4. Retrieval at scale

When brute-force DuckDB cosine gives way to an ANN index, and the 16GB in-RAM index
ceiling.

_(draft here)_

## 5. The v3 tripwire

The measured condition that ends the native-Mac era and justifies Docker + RunPod.

_(draft here)_
