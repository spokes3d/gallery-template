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
            plasma-plots = { git = "https://example.org/plasma-plots" }
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


def test_a_public_example_may_use_a_private_code(gallery):
    script = SCRIPT + "\nimport secretcode\n"
    folder = write_study(
        gallery.root, "07_example", script=script, kind="example", public=True
    )
    study = Study(folder)
    assert study.private_codes(gallery) == {"secretcode"}
    assert study.public_problems(gallery, local_modules(gallery)) == []
    # the private code is not a dependency of the public gallery
    target = gallery.root.parent / "public"
    export(gallery, target)
    assert "secretcode" not in (target / "pyproject.toml").read_text()
    assert (target / "studies" / "07_example" / "study.py").exists()


def test_a_public_verification_may_use_a_private_code(gallery):
    script = SCRIPT + "\nimport secretcode\n"
    folder = write_study(
        gallery.root, "08_check", script=script, kind="verification", public=True
    )
    assert Study(folder).public_problems(gallery, local_modules(gallery)) == []


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
    # a web figure, with its picture: the poster when kaleido draws none
    assert "import PlotlyFigure" in page
    assert '<PlotlyFigure src="/studies/squares/plot-1.plotly.json"' in page
    assert (site.public / "squares" / "plot-1.plotly.json").exists()
    assert "**Figure 1.** the squares" in page
    # the figures lead: intro, figures, status, the rest of the text, details, source
    order = [
        "It squares a few numbers",
        "plot-1.plotly.json",
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
    index = (site.studies / "index.mdx").read_text()
    assert "[Example](/private-gallery/by-kind/example/)" in index
    # the gallery: a card per study with its front figure, the stub's without one
    assert "import GalleryGrid" in index
    assert (
        '"thumbnail": {"kind": "plotly", "src": "/studies/squares/plot-1.plotly.json"}'
        in index
    )
    assert '"placeholder": "in development"' in index
    assert (site.content / "by-code" / "numpy.mdx").exists()
    assert (site.content / "by-kind" / "result.mdx").exists()
    by_code = (site.content / "by-code" / "secretcode.mdx").read_text()
    assert "Studies with secretcode" in by_code and "<GalleryGrid" in by_code
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
    assert "Our own introduction." in (site.studies / "index.mdx").read_text()


PROFILED = (
    SCRIPT.replace(
        'def simulate(preset="full"):\n',
        'def simulate(preset="full"):\n'
        "    import scope_profiler as sp\n"
        "    for _ in range(3):\n"
        '        with sp.region("squares.step"):\n'
        "            pass\n",
    )
    + """

def setup(preset):
    return {"Points": PRESETS[preset], "Model": "$y = x^2$"}


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--preset", default="full")
"""
)


def test_profile_setup_and_run_sections(gallery):
    folder = write_study(
        gallery.root, "08_profiled", script=PROFILED, codes=["numpy", "secretcode"]
    )
    (folder / "solver.c").write_text("int main(void) { return 0; }\n")
    meta = yaml.safe_load((folder / "study.yml").read_text())
    meta["sources"] = ["solver.c"]
    (folder / "study.yml").write_text(yaml.safe_dump(meta))
    build(gallery, ["08_profiled"])
    recorded = json.loads(folder.joinpath("results", "full.json").read_text())
    step = next(r for r in recorded["profile"] if r["region"] == "squares.step")
    assert step["calls"] == 3
    site = Site(gallery)
    page = (site.studies / "profiled.mdx").read_text()
    # the set-up of the preset, the profile of the run, and how to run it
    assert "| Points | 5 |" in page and "| Model | $y = x^2$ |" in page
    assert "## Profile" in page and "| `squares.step` | 3 |" in page
    assert "python study.py --preset full" in page
    numpy_version = recorded["codes"]["numpy"]["version"]
    assert f"numpy=={numpy_version}" in page and "matplotlib" in page
    assert "secretcode" not in page.split("pip install")[1].split("\n")[0]
    assert "It needs secretcode, which is not public" in page
    assert "`--preset smoke` checks the set-up" in page
    assert "[solver.c](/private-gallery/studies/profiled/solver.c)" in page
    assert (site.public / "profiled" / "study.py").read_text() == (
        folder / "study.py"
    ).read_text()
    assert (site.public / "profiled" / "solver.c").exists()
    order = [":::note[Status]", "## Set-up", "## Profile", "## Details", "## Run it"]
    assert [page.index(t) for t in order] == sorted(page.index(t) for t in order)


def test_profile_off_and_bad_setup(gallery):
    script = SCRIPT + "\n\ndef setup(preset):\n    return [1, 2]\n"
    write_study(gallery.root, "09_unprofiled", script=script, profile=False)
    with pytest.raises(GalleryError, match="must return a mapping"):
        build(gallery, ["09_unprofiled"])
    meta = json.loads(
        (gallery.studies_dir / "09_unprofiled" / "results" / "full.json").read_text()
    )
    assert "profile" not in meta
    # no --preset in the script: the command has none, and there is no profile section
    build(gallery, ["01_squares"])
    page = (Site(gallery).studies / "squares.mdx").read_text()
    assert "python study.py\n" in page and "## Profile" not in page
    study = Study(gallery.studies_dir / "09_unprofiled")
    study.meta["profile"] = "no"
    assert "study.yml: `profile` must be true or false" in study.problems(gallery)


def test_requirements_of_tools_and_commits(gallery):
    from gallery_tools.build import requirements
    from gallery_tools.config import TOOLS

    script = "from gallery_tools import native\n" + SCRIPT
    folder = write_study(gallery.root, "10_native", script=script)
    study = Study(folder)
    meta = {"codes": {"numpy": {"version": "2.0", "commit": "abc+dirty"}}}
    needed = requirements(Site(gallery), study, meta)
    assert TOOLS in needed and "numpy" in needed


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
    assert "plasma-plots[web]" in project["optional-dependencies"]["docs"]
    sources = tomllib.loads((target / "pyproject.toml").read_text())["tool"]["uv"]
    # the codes the public studies use, and plasma-plots for the web figures
    assert set(sources["sources"]) == {"numpy", "plasma-plots"}
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


def test_export_markers_and_system_packages(gallery, tmp_path):
    config = yaml.safe_load((gallery.root / "gallery.yml").read_text())
    config["public"]["apt_packages"] = ["gfortran", "cmake"]
    (gallery.root / "gallery.yml").write_text(yaml.safe_dump(config))
    pyproject = gallery.root / "pyproject.toml"
    pyproject.write_text(
        pyproject.read_text().replace(
            'requires-python = ">=3.11"\n',
            'requires-python = ">=3.11"\n'
            "optional-dependencies.new = [ \"NumPy[fast]; python_version>='3.12'\" ]\n",
        )
    )
    target = tmp_path / "public"
    export(load(gallery.root), target)
    project = tomllib.loads((target / "pyproject.toml").read_text())["project"]
    # the code keeps the marker of the private gallery, so the public project resolves
    assert "numpy; python_version>='3.12'" in project["dependencies"]
    assert "matplotlib" in project["dependencies"]
    tests = yaml.safe_load((target / ".github" / "workflows" / "tests.yml").read_text())
    steps = tests["jobs"]["studies"]["steps"]
    assert steps[1]["run"].endswith("apt-get install -y gfortran cmake")
    assert steps[2]["uses"].startswith("astral-sh/setup-uv")
    docs = yaml.safe_load((target / ".github" / "workflows" / "docs.yml").read_text())
    assert docs["jobs"]["docs"]["with"]["apt-packages"] == "gfortran cmake"
    assert "apt_packages" not in (target / "gallery.yml").read_text()


def test_export_without_system_packages(gallery, tmp_path):
    export(gallery, tmp_path / "public")
    tests = (tmp_path / "public" / ".github" / "workflows" / "tests.yml").read_text()
    assert "apt-get" not in tests


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


ANIMATED = (
    SCRIPT
    + """

def plot(result):
    from matplotlib.animation import FuncAnimation
    import plotly.graph_objects as go

    fig, ax = plt.subplots()
    fig.caption = "a moving point"
    (line,) = ax.plot(result["x"][:1], result["y"][:1], "o")
    ax.set_xlim(0, 5)
    ax.set_ylim(0, 25)

    def update(i):
        line.set_data(result["x"][i : i + 1], result["y"][i : i + 1])
        return (line,)

    extra = go.Figure(go.Scatter(x=[0, 1], y=[1, 0]), layout={"meta": {"caption": "a line"}})
    return [FuncAnimation(fig, update, frames=3), extra]
"""
)


@pytest.fixture
def no_posters(monkeypatch):
    """No kaleido pictures: the tests stay fast and need no browser."""
    import plasma_plots.plotly_backend

    def fail(*args, **kwargs):
        raise RuntimeError("no browser")

    monkeypatch.setattr(plasma_plots.plotly_backend, "save_posters", fail)


def test_animation_and_returned_figures(gallery, no_posters):
    write_study(gallery.root, "04_animated", script=ANIMATED, figures=[])
    with pytest.warns(UserWarning, match="no posters"):
        build(gallery, ["04_animated"])
    site = Site(gallery)
    page = (site.studies / "animated.mdx").read_text()
    assert "**Figure 1.** a moving point" in page
    assert "**Figure 2.** a line" in page
    web = json.loads((site.public / "animated" / "plot-1.plotly.json").read_text())
    assert len(web["frames"]) == 3
    # the picture of the animation's figure is its poster; a Plotly figure has none
    assert 'poster="/studies/animated/plot-1.png"' in page
    assert (site.public / "animated" / "plot-2.plotly.json").exists()
    assert not (site.public / "animated" / "plot-2.png").exists()


def test_a_figure_that_cannot_be_converted_is_a_picture(gallery, monkeypatch):
    import gallery_tools.figures

    def fail(item):
        raise ValueError("not convertible")

    monkeypatch.setattr(gallery_tools.figures, "to_plotly", fail)
    with pytest.warns(UserWarning, match="written as a picture"):
        build(gallery, ["01_squares"])
    page = (Site(gallery).studies / "squares.mdx").read_text()
    assert "PlotlyFigure" not in page
    assert "](/private-gallery/studies/squares/plot-1.png)" in page


def test_without_plasma_plots_a_figure_is_a_picture(gallery, monkeypatch):
    import gallery_tools.figures

    def missing(item):
        raise ImportError("plasma_plots")

    monkeypatch.setattr(gallery_tools.figures, "to_plotly", missing)
    build(gallery, ["01_squares"])
    page = (Site(gallery).studies / "squares.mdx").read_text()
    assert "](/private-gallery/studies/squares/plot-1.png)" in page


def test_front_figure(gallery):
    script = SCRIPT + "\n    plt.figure()\n    plt.plot(result['y'], result['x'])\n"
    write_study(
        gallery.root, "08_two", script=script, figures=["one", "two"], front_figure=2
    )
    build(gallery, ["08_two"], rerun=["08_two"])
    assert (
        "/studies/two/plot-2.plotly.json"
        in (Site(gallery).studies / "index.mdx").read_text()
    )


def test_front_figure_errors(gallery):
    folder = write_study(gallery.root, "09_bad", front_figure=0)
    assert any("front_figure" in p for p in Study(folder).problems(gallery))
    write_study(gallery.root, "10_far", front_figure=3)
    with pytest.raises(GalleryError, match="front_figure 3"):
        build(gallery, ["10_far"], rerun=["10_far"])


C_PROGRAM = """
#include <stdio.h>
#include <stdlib.h>
#include "scale.h"
int main(int argc, char **argv) {
  char line[32] = "0";
  if (argc < 2) { fprintf(stderr, "no count\\n"); return 3; }
  fgets(line, sizeof line, stdin);
  for (int i = 0; i < atoi(argv[1]); i++) printf("%d\\n", SCALE * i * i + atoi(line));
  return 0;
}
"""

NATIVE_SCRIPT = '''
"""Squares in C.

A program in C squares the numbers.
"""

import matplotlib.pyplot as plt

from gallery_tools import native

PRESETS = {"smoke": 3, "full": 5}


def simulate(preset="full"):
    printed = native.run(["scale.h", "squares.c"], PRESETS[preset])
    return {"y": [int(line) for line in printed.split()]}


def plot(result):
    plt.plot(result["y"])
'''


def write_native_study(root: Path, stem: str = "08_native", **meta) -> Path:
    """A study whose program is in C, with a header."""
    folder = write_study(
        root, stem, script=NATIVE_SCRIPT, sources=["*.c", "scale.h", "*.c"], **meta
    )
    (folder / "squares.c").write_text(C_PROGRAM)
    (folder / "scale.h").write_text("#define SCALE 2\n")
    return folder


def test_native_runs_a_c_program(tmp_path, monkeypatch):
    from gallery_tools import native

    monkeypatch.setattr(native.tempfile, "gettempdir", lambda: str(tmp_path / "tmp"))
    folder = write_native_study(tmp_path)
    monkeypatch.chdir(folder)
    assert native.run(["scale.h", "squares.c"], 3).split() == ["0", "2", "8"]
    executable = native.build(["scale.h", "squares.c"])
    built = executable.stat().st_mtime_ns
    # kept until a source, a header or a flag changes
    assert native.build(["scale.h", "squares.c"]).stat().st_mtime_ns == built
    assert native.build(["scale.h", "squares.c"], flags=["-O0"]) != executable
    (folder / "scale.h").write_text("#define SCALE 3\n")
    assert native.run(
        ["scale.h", "squares.c"], 3, stdin="1\n", cwd=tmp_path
    ).split() == [
        "1",
        "4",
        "13",
    ]
    assert native.run(["scale.h", "squares.c"], 1, env={"A": "b"}) == "0\n"
    with pytest.raises(GalleryError, match="(?s)running squares.c failed.*no count"):
        native.run(["scale.h", "squares.c"])
    (folder / "broken.c").write_text("int main( {")
    with pytest.raises(GalleryError, match="compiling broken.c failed"):
        native.run("broken.c")
    with pytest.raises(GalleryError, match="no source file"):
        native.run("missing.c")
    (folder / "other.jl").write_text("")
    with pytest.raises(GalleryError, match="one language"):
        native.run(["squares.c", "other.jl"])
    with pytest.raises(GalleryError, match="one language"):
        native.run("study.yml")
    with pytest.raises(GalleryError, match="not compiled"):
        native.build("other.jl")


def test_native_languages_and_toolchain(tmp_path, monkeypatch):
    from gallery_tools import native

    assert native.language_of("a/solver.F90").name == "Fortran"
    assert native.language_of("notes.txt") is None
    fences = {
        "main.cpp": "cpp",
        "a.h": "c",
        "run.jl": "julia",
        "Makefile": "makefile",
        "Project.toml": "toml",
        "data.dat": "text",
    }
    assert {name: native.fence_of(name) for name in fences} == fences
    # an interpreter: a stand-in for julia that echoes its command line
    fake = tmp_path / "fakejulia"
    fake.write_text('#!/bin/sh\necho "$@"\n')
    fake.chmod(0o755)
    monkeypatch.setenv("JULIA", f"{fake} --threads=2")
    script = tmp_path / "model.jl"
    script.write_text("")
    assert native.run(script, 4).split() == [
        "--threads=2",
        "--startup-file=no",
        str(script),
        "4",
    ]
    (tmp_path / "Project.toml").write_text("")
    assert f"--project={tmp_path}" in native.run(script, flags=[])
    assert native.toolchain([script, script, "x.txt"]) == {
        "Julia": "--threads=2 --version"
    }
    # nothing installed: an error that says what to do, and no record
    monkeypatch.setenv("JULIA", "no-such-julia")
    with pytest.raises(native.ToolchainError, match="no Julia interpreter.*set JULIA"):
        native.run(script)
    assert native.toolchain([script]) == {}
    monkeypatch.delenv("JULIA")
    monkeypatch.setattr(native.shutil, "which", lambda name: None)
    with pytest.raises(native.ToolchainError, match="tried gfortran, flang, ifx"):
        native.command(native.LANGUAGES["fortran"])
    silent = tmp_path / "silent"
    silent.write_text("#!/bin/sh\n")
    silent.chmod(0o755)
    monkeypatch.undo()
    monkeypatch.setenv("FC", str(silent))
    assert native.version(native.LANGUAGES["fortran"]) == "unknown"


def test_a_study_in_another_language(gallery, tmp_path, monkeypatch):
    from gallery_tools import native

    monkeypatch.setattr(native.tempfile, "gettempdir", lambda: str(tmp_path / "tmp"))
    folder = write_native_study(gallery.root, public=True)
    study = Study(folder)
    assert [p.name for p in study.sources] == ["squares.c", "scale.h"]
    assert not study.problems(gallery)
    assert not study.public_problems(gallery, local_modules(gallery))
    build(gallery, ["08_native"])
    assert "C" in json.loads(study.cache("full")[1].read_text())["toolchain"]
    page = (Site(gallery).studies / "native.mdx").read_text()
    assert "| Compilers | C: " in page
    assert "## C source: `squares.c`" in page and "```c\n" in page
    assert page.index("## Python source") < page.index("## C source: `scale.h`")
    (folder / "notes.txt").write_text("plain")
    meta = yaml.safe_load((folder / "study.yml").read_text())
    (folder / "study.yml").write_text(yaml.safe_dump(meta | {"sources": ["notes.txt"]}))
    build(gallery, ["08_native"])
    page = (Site(gallery).studies / "native.mdx").read_text()
    assert "## Source: `notes.txt`" in page and "```text\nplain" in page
    # the sources are published with the study, and the tools are not required twice
    target = tmp_path / "public"
    export(gallery, target)
    assert (target / "studies" / "08_native" / "squares.c").exists()
    project = tomllib.loads((target / "pyproject.toml").read_text())["project"]
    assert sum("gallery-tools" in d for d in project["dependencies"]) == 1
    # what `sources` must be
    for sources, message in (
        ("squares.c", "must be a list"),
        (["missing.f90"], "no file 'missing.f90'"),
        (["../../gallery.yml"], "no file '../../gallery.yml'"),
    ):
        meta = yaml.safe_load((folder / "study.yml").read_text())
        meta["sources"] = sources
        (folder / "study.yml").write_text(yaml.safe_dump(meta))
        assert message in " ".join(Study(folder).problems(gallery))
        assert Study(folder).sources == []
