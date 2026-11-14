"""The tests every gallery runs on its studies, imported by its ``tests/test_studies.py``.

::

    from gallery_tools.testing import *  # noqa: F403

Each study is well formed, its docs result is cached, it runs end to end in its tiny ``smoke``
preset with one caption per figure, and a public study can go public. The gallery is found from
the working directory (``gallery.yml``).
"""

from __future__ import annotations

import os
import pickle
import runpy
from contextlib import contextmanager
from pathlib import Path

import pytest

from gallery_tools.config import load
from gallery_tools.figures import collect
from gallery_tools.study import Study, discover, local_modules

__all__ = [
    "test_docs_result_is_cached",
    "test_public_study_can_go_public",
    "test_study_is_well_formed",
    "test_study_runs_in_smoke_preset",
]

GALLERY = load()
STUDIES = discover(GALLERY)
IDS = [s.stem for s in STUDIES]


@contextmanager
def _in_folder(folder: Path):
    """Run in the study's folder, as the builder does."""
    previous = Path.cwd()
    os.chdir(folder)
    try:
        yield
    finally:
        os.chdir(previous)


@pytest.mark.parametrize("study", STUDIES, ids=IDS)
def test_study_is_well_formed(study: Study):
    """study.yml is complete and the script has its docstring and presets."""
    assert not study.problems(GALLERY)


@pytest.mark.parametrize("study", STUDIES, ids=IDS)
def test_docs_result_is_cached(study: Study):
    """The docs build never runs a simulation: the result of the docs preset is committed."""
    if study.stub:
        pytest.skip("a stub has no result")
    result, meta = study.cache(study.preset)
    assert result.exists() and meta.exists(), (
        f"no cached {study.preset!r} result for {study.stem}: run "
        f"`gallery build {study.stem} --rerun {study.stem}`"
    )


@pytest.mark.parametrize("study", STUDIES, ids=IDS)
def test_public_study_can_go_public(study: Study):
    """A study marked public meets the rules of the public gallery."""
    if not study.public or GALLERY.public is None:
        pytest.skip("not public, or this gallery publishes nothing")
    assert not study.public_problems(GALLERY, local_modules(GALLERY))


@pytest.mark.parametrize("study", STUDIES, ids=IDS)
def test_study_runs_in_smoke_preset(study: Study):
    """The study runs in its smoke preset and every figure has a caption."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    if study.stub:
        pytest.skip("a stub does not run")
    with _in_folder(study.folder):
        try:
            namespace = runpy.run_path(str(study.source), run_name="gallery_study")
            result = namespace["simulate"]("smoke")
        except ImportError as error:  # codes a study imports only when it runs
            pytest.skip(f"a code the study needs is not installed: {error}")
        pickle.loads(pickle.dumps(result, protocol=4))  # the cache stores it
        plt.close("all")
        returned = namespace["plot"](result)
        figures = collect(returned)
        captions = study.captions(figures)
        plt.close("all")
    assert len(study.meta.get("figures") or []) <= len(figures), (
        "study.yml has more captions than plot draws figures"
    )
    missing = [i + 1 for i, caption in enumerate(captions) if not caption]
    assert not missing, (
        f"figures {missing} have no caption (fig.caption or `figures` in study.yml)"
    )
    if "table" in namespace:
        assert "|" in namespace["table"](result)
