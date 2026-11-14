"""Unit tests of the gallery tools on small galleries written into a temporary folder."""

import json
import textwrap
import tomllib
from pathlib import Path

import pytest
import yaml

from gallery_tools import GalleryError, cli, load
from gallery_tools.build import Site, build, fmt_seconds, provenance, source_fence
from gallery_tools.export import check_public, export
from gallery_tools.study import Study, discover, local_modules

SCRIPT = '''
"""A tiny study.

It squares a few numbers. $x^2$ and {braces}.

How it squares them: one at a time.
"""

import matplotlib.pyplot as plt
import numpy as np

PRESETS = {"smoke": 3, "full": 5}


def simulate(preset="full"):
    x = np.arange(PRESETS[preset])
    return {"x": x, "y": x**2}


def plot(result):
    print("printed by plot")
    plt.plot(result["x"], result["y"])
'''

CONFIG = {
    "site": {"title": "Test", "owner": "me", "repo": "private-gallery"},
    "codes": ["numpy"],
    "private_codes": ["secretcode"],
    "fields": {"ladder": {"label": "Rung", "link": "/programme/", "default": "none"}},
    "public": {
        "owner": "me",
        "repo": "public-gallery",
        "title": "Public",
        "description": "The public studies.",
    },
}


def write_study(root: Path, stem: str, script: str = SCRIPT, **meta) -> Path:
    """A study folder with its script and study.yml."""
    folder = root / "studies" / stem
    folder.mkdir(parents=True)
    (folder / "study.py").write_text(textwrap.dedent(script))
    info = {
        "category": "Tests",
        "kind": "example",
        "public": False,
        "codes": ["numpy"],
        "status": "A test.",
        "docs_preset": "full",
        "figures": ["the squares"],
        **meta,
    }
    (folder / "study.yml").write_text(yaml.safe_dump(info))
    return folder


@pytest.fixture
def gallery(tmp_path):
    """A private gallery with a public, a private and a stub study."""
    root = tmp_path / "private"
    root.mkdir()
    (root / "gallery.yml").write_text(yaml.safe_dump(CONFIG))
    (root / "pyproject.toml").write_text(
        textwrap.dedent(
            """
            [project]
            name = "private"
            requires-python = ">=3.11"
            [tool.uv.sources]
            numpy = { git = "https://example.org/numpy", branch = "devel" }
            other = { git = "https://example.org/other" }
            """
        )
    )
    docs = root / "docs"
    (docs / "src").mkdir(parents=True)
    (docs / "package.json").write_text("{}")
    (docs / "src" / "content.config.ts").write_text("export {};")
    (root / "public" / "docs").mkdir(parents=True)
    (root / "public" / "docs" / "extra.txt").write_text("overlay")
    public = write_study(root, "01_squares", public=True, ladder="1a")
    (public / "data").mkdir()
    (public / "data" / "keep.txt").write_text("kept")
    (public / "secret").mkdir()
    (public / "secret" / "raw.txt").write_text("private")
    meta = yaml.safe_load((public / "study.yml").read_text())
    meta["exclude"] = ["secret/"]
    (public / "study.yml").write_text(yaml.safe_dump(meta))
    write_study(root, "02_private")
    stub = root / "studies" / "03_stub"
    stub.mkdir()
    (stub / "study.py").write_text('"""A stub.\n\nNot yet run.\n"""\n')
    (stub / "study.yml").write_text(
        yaml.safe_dump(
            {
                "category": "Later",
                "kind": "result",
                "public": False,
                "codes": ["secretcode"],
                "status": "Not run.",
                "stub": True,
            }
        )
    )
    return load(root)


def test_load_and_find_root(gallery, monkeypatch):
    monkeypatch.chdir(gallery.studies_dir / "01_squares")
    found = load()
    assert found.root == gallery.root
    assert found.base == "/private-gallery"
    assert found.public.repo == "public-gallery"


def test_load_errors(tmp_path):
    with pytest.raises(GalleryError, match="no gallery.yml"):
        load(tmp_path)
    (tmp_path / "gallery.yml").write_text("site: {title: x}\n")
    with pytest.raises(GalleryError, match="site.owner"):
        load(tmp_path)
    (tmp_path / "gallery.yml").write_text(
        "site: {title: x, owner: o, repo: r}\npublic: {repo: r}\n"
    )
    with pytest.raises(GalleryError, match="public"):
        load(tmp_path)


def test_discover_and_read(gallery):
    studies = discover(gallery)
    assert [s.stem for s in studies] == ["01_squares", "02_private", "03_stub"]
    squares = studies[0]
    assert squares.slug == "squares" and squares.order == 1
    assert squares.title == "A tiny study"
    assert squares.summary == "It squares a few numbers"
    assert squares.presets == ["smoke", "full"]
    assert squares.public and not squares.stub
    assert squares.third_party() == {"matplotlib", "numpy"}
    assert all(not s.problems(gallery) for s in studies)


def test_missing_files(gallery):
    folder = gallery.studies_dir / "04_broken"
    folder.mkdir()
    with pytest.raises(GalleryError, match="no study.py"):
        Study(folder)
    (folder / "study.py").write_text("x = 1\n")
    with pytest.raises(GalleryError, match="no study.yml"):
        Study(folder)


def test_problems(gallery):
    folder = write_study(
        gallery.root,
        "05_bad",
        script="PRESETS = {'quick': 1}\n",
        kind="novel",
        public="yes",
        codes="numpy",
        unknown=1,
        figures=None,
    )
    meta = yaml.safe_load((folder / "study.yml").read_text())
    del meta["status"]
    (folder / "study.yml").write_text(yaml.safe_dump(meta))
    problems = " | ".join(Study(folder).problems(gallery))
    for text in (
        "docstring",
        "'status'",
        "unknown keys ['unknown']",
        "kind 'novel'",
        "public must be",
        "codes must be a list",
        "'smoke' preset",
        "docs_preset 'full'",
        "figures",
    ):
        assert text in problems


def test_public_problems(gallery):
    (gallery.root / "helpers.py").write_text("X = 1\n")
    script = SCRIPT + "\nimport helpers\nimport secretcode\n"
    folder = write_study(
        gallery.root, "06_leaky", script=script, kind="result", public=True
    )
    study = Study(folder)
    problems = " | ".join(study.public_problems(gallery, local_modules(gallery)))
    assert "preprint" in problems
    assert "private codes ['secretcode']" in problems
    assert "['helpers']" in problems
    stub = Study(gallery.studies_dir / "03_stub")
    assert "stub" in " ".join(stub.public_problems(gallery, set()))
    assert "06_leaky" in check_public(gallery)
    with pytest.raises(GalleryError, match="cannot go public"):
        export(gallery, gallery.root.parent / "public")


def test_build(gallery, capsys):
    built = build(gallery)  # runs the simulations: nothing is cached yet
    assert [s.stem for s in built] == ["01_squares", "02_private", "03_stub"]
    result, meta = built[0].cache("full")
    assert result.exists()
    assert "numpy" in json.loads(meta.read_text())["codes"]
    site = Site(gallery)
    page = (site.studies / "squares.mdx").read_text()
    assert "| Rung | 1a ([about](/private-gallery/programme/)) |" in page
    assert "printed by plot" in page
    assert "/private-gallery/studies/squares/plot-1.png" in page
    assert "**Figure 1.** the squares" in page
    # the figures lead: intro, figures, status, the rest of the text, details, source
    order = [
        "It squares a few numbers",
        "plot-1.png",
        ":::note[Status]",
        "How it squares them",
        "## Details",
        "## Python source",
    ]
    assert [page.index(text) for text in order] == sorted(
        page.index(text) for text in order
    )
    assert (site.public / "squares" / "plot-1.png").exists()
    assert "in development, not run" in (site.studies / "stub.mdx").read_text()
    index = (site.studies / "index.md").read_text()
    assert "[Example](/private-gallery/by-kind/example/)" in index
    assert (site.content / "by-code" / "numpy.md").exists()
    assert (site.content / "by-kind" / "result.md").exists()
    assert (
        "Studies with secretcode"
        in (site.content / "by-code" / "secretcode.md").read_text()
    )
    # cached now: a partial build with --cached-only does not run anything
    build(gallery, ["01_squares"], cached_only=True)
    assert "cached full result" in capsys.readouterr().out


def test_build_errors(gallery):
    with pytest.raises(GalleryError, match="unknown studies"):
        build(gallery, ["99_none"])
    with pytest.raises(GalleryError, match="no cached"):
        build(gallery, ["01_squares"], cached_only=True)


def test_build_table_and_intro(gallery):
    script = SCRIPT + '\n\ndef table(result):\n    return "| a |\\n|---|\\n| 1 |"\n'
    write_study(gallery.root, "07_table", script=script)
    (gallery.docs / "studies-intro.md").write_text("Our own introduction.")
    build(gallery, ["07_table"], rerun=["07_table"])
    site = Site(gallery)
    page = (site.studies / "table.mdx").read_text()
    assert "## Comparison" in page and "Printed output" not in page
    assert "Our own introduction." in (site.studies / "index.md").read_text()


def test_export(gallery, tmp_path):
    build(gallery, ["01_squares"])
    target = tmp_path / "public"
    (target / ".git").mkdir(parents=True)
    (target / "stale.txt").write_text("removed")
    (target / "olddir").mkdir()
    (target / ".venv").mkdir()
    (target / "docs" / "node_modules").mkdir(parents=True)
    (target / "docs" / "stale.md").write_text("removed")
    exported = export(gallery, target)
    assert (target / ".venv").is_dir() and (target / "docs" / "node_modules").is_dir()
    assert not (target / "docs" / "stale.md").exists()
    assert [s.stem for s in exported] == ["01_squares"]
    assert (target / ".git").is_dir()
    assert not (target / "stale.txt").exists() and not (target / "olddir").exists()
    study = target / "studies" / "01_squares"
    assert (study / "data" / "keep.txt").exists()
    assert (study / "results" / "full.pkl").exists()
    assert not (study / "secret").exists()
    assert not (target / "studies" / "02_private").exists()
    config = load(target)
    assert config.repo == "public-gallery" and config.public is None
    assert config.fields["ladder"]["label"] == "Rung"
    assert (
        "link" not in config.fields["ladder"]
    )  # the programme page does not go public
    project = tomllib.loads((target / "pyproject.toml").read_text())["project"]
    assert project["name"] == "public-gallery"
    assert any(d.startswith("gallery-tools @") for d in project["dependencies"])
    assert {"matplotlib", "numpy"} <= set(project["dependencies"])
    sources = tomllib.loads((target / "pyproject.toml").read_text())["tool"]["uv"]
    assert set(sources["sources"]) == {"numpy"}
    astro = (target / "docs" / "astro.config.mjs").read_text()
    assert 'repo: "public-gallery"' in astro
    assert (target / "docs" / "package.json").exists()
    assert (target / "docs" / "extra.txt").read_text() == "overlay"
    assert (target / ".github" / "workflows" / "sync_pr.yml").exists()
    assert (target / ".github" / "workflows" / "sync_merge.yml").exists()
    assert (target / "tests" / "test_studies.py").exists()
    assert "public-gallery/studies/squares/" in (target / "README.md").read_text()
    stamp = json.loads((target / ".gallery-export.json").read_text())
    assert (
        stamp["studies"] == ["01_squares"] and stamp["source"] == "me/private-gallery"
    )
    # the exported gallery is itself a well-formed gallery
    public = load(target)
    assert [s.stem for s in discover(public)] == ["01_squares"]
    assert not discover(public)[0].problems(public)


def test_export_keeps_links_to_public_pages(gallery, tmp_path):
    pages = gallery.root / "public" / "docs" / "src" / "content" / "docs"
    pages.mkdir(parents=True)
    (pages / "programme.mdx").write_text("---\ntitle: Programme\n---\n")
    export(gallery, tmp_path / "public")
    assert load(tmp_path / "public").fields["ladder"]["link"] == "/programme/"


def test_export_errors(gallery, tmp_path):
    with pytest.raises(GalleryError, match="outside the gallery"):
        export(gallery, gallery.root / "public-out")
    (gallery.root / "gallery.yml").write_text(
        yaml.safe_dump({k: v for k, v in CONFIG.items() if k != "public"})
    )
    with pytest.raises(GalleryError, match="no `public:`"):
        export(load(gallery.root), tmp_path / "out")


def test_cli(gallery, tmp_path, capsys):
    root = ["--root", str(gallery.root)]
    assert cli.main([*root, "check"]) == 0
    assert "3 studies, 1 public, 0 problems" in capsys.readouterr().out
    assert cli.main([*root, "list", "--public"]) == 0
    out = capsys.readouterr().out
    assert "01_squares" in out and "02_private" not in out
    assert cli.main([*root, "list"]) == 0
    assert "02_private" in capsys.readouterr().out
    assert cli.main([*root, "build", "01_squares", "--rerun"]) == 0
    assert cli.main([*root, "export", str(tmp_path / "out")]) == 0
    assert "exported 1 public studies" in capsys.readouterr().out
    assert cli.main([*root, "build", "99_none"]) == 1
    assert "unknown studies" in capsys.readouterr().err
    write_study(gallery.root, "08_bad", kind="novel", public=True)
    assert cli.main([*root, "check"]) == 1
    assert "08_bad (public)" in capsys.readouterr().out


def test_helpers():
    assert fmt_seconds(10) == "10 s"
    assert fmt_seconds(600) == "10 min"
    assert fmt_seconds(7200) == "2.0 h"
    assert source_fence("a = '```'").startswith("````python")
    assert provenance(["numpy", "not-a-distribution"])["numpy"]["version"]


def test_captions_of_the_figures(gallery):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    study = Study(gallery.studies_dir / "01_squares")
    own, listed, bare = plt.figure(), plt.figure(), plt.figure()
    own.caption = "its own caption"
    try:
        # its own caption wins over study.yml; a figure past the list has none
        assert study.captions([own, listed, bare]) == [
            "its own caption",
            None,
            None,
        ]
        assert study.captions([listed, own]) == ["the squares", "its own caption"]
    finally:
        plt.close("all")
