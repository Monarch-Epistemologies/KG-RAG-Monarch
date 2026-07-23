#!/usr/bin/env python3
"""Load a sentence-embedding model with the pooling its family was trained for.

SapBERT and MedCPT are PubMedBERT-family encoders trained on the [CLS] token; loading
them through sentence-transformers' default mean pooling would understate them. Build
those with CLS pooling; let native sentence-transformer models (MiniLM, BioLORD) bring
their own. Shared by the synonym eval and the corpus embedding step so both load a
given model the same way. See eval/README.md for why pooling is not a free choice.
"""

from sentence_transformers import SentenceTransformer, models

# Substrings that mark a PubMedBERT-family encoder needing CLS pooling.
CLS_POOLED = ("sapbert", "pubmedbert", "medcpt")


def needs_cls(name):
    return any(tag in name.lower() for tag in CLS_POOLED)


def build_model(name, device="mps"):
    if needs_cls(name):
        word = models.Transformer(name)
        pooling = models.Pooling(
            word.get_word_embedding_dimension(),
            pooling_mode_cls_token=True,
            pooling_mode_mean_tokens=False,
        )
        return SentenceTransformer(modules=[word, pooling], device=device)
    return SentenceTransformer(name, device=device)
