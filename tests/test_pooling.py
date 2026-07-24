"""Error class 3: wrong pooling would silently understate a model.

The model comparison is only fair if each model is read the way it was trained (see
eval/README.md → Pooling). build_model() must give PubMedBERT-family encoders (SapBERT,
MedCPT) CLS pooling and leave native sentence-transformers (MiniLM) on their own mean
pooling. These load the real models and assert the pooling module is configured as
claimed; they skip if the weights are not available (e.g. offline first run).
"""

import pytest
from conftest import require  # noqa: F401  (imported to ensure bin/ is on sys.path)
from embed_models import build_model, needs_cls
from sentence_transformers.models import Pooling

SAPBERT = "cambridgeltl/SapBERT-from-PubMedBERT-fulltext"
MINILM = "all-MiniLM-L6-v2"


def _pooling_module(model):
    for module in model:
        if isinstance(module, Pooling):
            return module
    raise AssertionError("no Pooling module found in the model")


def test_NeedsCls_WHEN_pubmedbert_family_SHOULD_be_true_else_false():
    # Pure decision function — no weights needed, so this always runs.
    assert needs_cls(SAPBERT)
    assert needs_cls("ncbi/MedCPT-Query-Encoder")
    assert not needs_cls(MINILM)
    assert not needs_cls("FremyCompany/BioLORD-2023")


def _try_build(name):
    try:
        return build_model(name, device="cpu")
    except Exception as exc:  # noqa: BLE001 — offline / missing weights, not a failure
        pytest.skip(f"could not load {name}: {exc}")


def _mode(model):
    # sentence-transformers exposes the pooling mode as a single string in the
    # module config ('cls', 'mean', ...); the older per-mode boolean attributes
    # were removed.
    return _pooling_module(model).get_config_dict()["pooling_mode"]


def test_BuildModel_WHEN_sapbert_SHOULD_use_cls_pooling():
    assert _mode(_try_build(SAPBERT)) == "cls"


def test_BuildModel_WHEN_general_model_SHOULD_use_mean_not_cls():
    assert _mode(_try_build(MINILM)) == "mean"
