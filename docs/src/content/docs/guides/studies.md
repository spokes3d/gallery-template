---
title: Adding a study
description: The study script, study.yml, the presets and the cache of results.
---

A study is a folder `studies/<nn>_<name>/`, where `<nn>` is its place in the listing. Its page
shows the complete source of `study.py`, so the script is standalone: it imports the codes and
nothing else from the repository, and it shows the whole set-up. Data it reads go into the
folder (`data/`), next to the script.

## study.py

```python
"""Title of the study, on one line.

What the study does and what the figures show. Markdown and $math$ work.

Compared: what the result is compared with, and what is not compared.

Reference: the paper or the case it follows.
"""

import argparse

import matplotlib.pyplot as plt
import plasma_plots

PRESETS = {"smoke": ..., "quick": ..., "full": ...}  # the sizes; "smoke" is required


def simulate(preset: str = "quick") -> dict:
    """Run the preset; return plain data (numpy arrays, xarray, numbers, dicts)."""


def plot(result: dict) -> None:
    """Draw the figures and leave them open, each with a caption."""
    with plasma_plots.figure(caption="What the figure shows.") as fig:
        ...


def table(result: dict) -> str:  # optional: a Markdown table the page shows
    ...


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--preset", choices=sorted(PRESETS), default="quick")
    args = parser.parse_args()
    plot(simulate(args.preset))
    plt.show()
```

The result of `simulate` must be picklable and must not depend on the script (use `asdict` of
a dataclass, not the dataclass): the cache stores it, and `plot` has to work from the cache
alone. Everything `plot` prints appears on the page, unless there is a `table`.

The figures lead the page: the first paragraph of the docstring, then the figures, numbered,
each with its caption, then the status and the rest of the text. A figure's caption is its own,
`plasma_plots.figure(caption=...)` or maxplotlib's `Canvas(caption=...)` (both set
`fig.caption`), else its entry in `figures` of `study.yml`; the test fails on a figure without
one. Write the caption to be read without the text: what is plotted against what, and what to
see in it. The builder runs the script in its folder, so relative paths start there.

The Studies page is a gallery, the theme's `GalleryGrid`: a card per study, under its category,
with its front figure (the first unless `front_figure` in `study.yml` names another), title,
kind, codes and summary, and a filter box. Pick the figure that shows the study at a glance and
reads at the size of a card. The pages per kind and per code show their studies the same way.

### Web figures

**Web figures are the standard: draw every figure so that it can be one.** The builder turns each
figure into an interactive Plotly figure in the site's colours (zoom, hover values, light and
dark mode), with pictures of it shown while it loads. plasma-plots converts the figures: draw
them with plasma-plots (`plasma_plots.figure(...)`, the `.plasma.plot` accessors) or with plain
Matplotlib (lines, scatter, `pcolormesh`, `imshow` with a colormap, contours, colorbars). A
figure with any part the conversion cannot handle is shown as a picture instead, with a warning
in the build (the conversion is strict, so a web figure never lacks a part); change the figure
rather than accept the picture where you can.

For something that moves, return an animation from `plot`: a Matplotlib `FuncAnimation`
becomes a web figure with a slider and a Play button (keep the frames few, a few dozen, and the
grids small, since every frame is in the page's data). `plot` may also return Plotly figures,
or a list of figures and animations:

```python
def plot(result: dict):
    fig, ax = plt.subplots()
    fig.caption = "The potential over one period, in the lab frame."
    image = ax.imshow(result["phi"][0])

    def update(i):
        image.set_data(result["phi"][i])
        return (image,)

    return FuncAnimation(fig, update, frames=len(result["phi"]))
```

## study.yml

```yaml
category: Global models      # the group in the listing
kind: verification           # verification, method, example, benchmark or result
public: false                # goes to the public gallery (see Publishing studies)
preprint: arXiv:2701.01234   # a `result` needs it before it is public
codes: [wellbalanced]        # Python codes: versions and commits are recorded with the result
external_codes:              # codes outside Python, written by hand
  SAPIC: v0.3.0 @ 1a2b3c4
docs_preset: full            # the preset the page shows
runtime: about 3 minutes
status: >-                   # what it verifies and what it does not, honestly
  Not a verification: ...
figures:                     # captions, in the order plot draws the figures, for
  - caption of figure 1      # figures without their own (plain Matplotlib)
front_figure: 2              # the figure on the study's card in the gallery (default 1)
exclude: [data/raw/]         # files that stay private when the study is published
stub: false                  # announced, not yet run: no simulate and plot needed
```

The keys a gallery adds (in the template: `level`) are declared under `fields` in
`gallery.yml`, with the label of their row in the table of the page.

The kinds:

| Kind | For | Public |
|---|---|---|
| verification | a code against an analytic result, a benchmark case or another code | at once |
| method | a demonstration of a numerical method or a feature | at once |
| example | a use of the codes, an estimate | at once |
| benchmark | run-level performance: scaling, hardware, codes against each other | at once |
| result | a novel result a paper will use | with its preprint |

## Status

Say what the study verifies and what it does not. A run that breaks a stability limit, is too
short to reach the steady state or has placeholder data is not a verification, and the status
box under the figures is where that is said.

## The cache

A simulation runs **only** when its result is not cached, or when it is asked for:

```bash
uv run gallery build                       # all studies; the cache first
uv run gallery build <stem> --rerun <stem> # rerun one study, refill its cache
uv run gallery build --preset smoke        # another preset, cached separately
```

The result of the docs preset is stored in `results/<preset>.pkl`, with the run time, the date
and the versions and git commits of the codes in `results/<preset>.json`. **Commit both**: CI
builds the site with `--cached-only` and fails rather than run a simulation. The `smoke` results
are not committed. A result says `+dirty` after a commit when the code had uncommitted changes,
which is worth fixing before a result is kept. The pickle is read back by the builder, so only
commit results you produced yourself.

## Checklist

1. The docstring gives the title, the description, what is compared and the reference.
2. `study.yml` is complete, with a caption for every figure and an honest status.
3. `python studies/<stem>/study.py --preset smoke` works, and takes seconds.
4. `uv run gallery check`, `uv run pytest`.
5. `uv run gallery build <stem> --rerun <stem>`, then look at the page.
