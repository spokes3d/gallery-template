# gallery-template

[![Tests](https://github.com/spokes3d/gallery-template/actions/workflows/tests.yml/badge.svg)](https://github.com/spokes3d/gallery-template/actions/workflows/tests.yml)
[![Docs](https://github.com/spokes3d/gallery-template/actions/workflows/docs.yml/badge.svg)](https://spokes3d.github.io/gallery-template/)

The skeleton of a gallery of computational studies, and the tools that run it (`gallery-tools`).
A study is a standalone script with its result cached and a status box that says what it
verifies and what it does not; the site (Astro + Starlight, the max-models theme) is built from
the cached results, so CI never reruns a long simulation.

A project keeps every study in a **private gallery** and publishes some of them in a **public
gallery**, generated from the private one: a study marked `public: true` goes there as a pull
request, once it meets the rules (a novel result needs its preprint, no private codes, no
helper modules).

Documentation: <https://spokes3d.github.io/gallery-template/>

## Commands

```bash
uv sync --extra dev
uv run gallery check                        # study.yml of every study, and the public rules
uv run gallery build                        # the Studies pages, cache first
uv run gallery build --cached-only          # as in CI: never run a simulation
uv run gallery export ../public-gallery     # the public gallery (the sync workflow does this)
uv run pytest                               # the tools' tests and every study's smoke preset
make docs-dev                               # the site at http://localhost:4321/gallery-template/
```

## Layout

| Path | What |
|---|---|
| `src/gallery_tools/` | the tools: `gallery check`, `build`, `export`, `list`, and the shared study tests |
| `studies/01_exponential_decay/` | the example study: `study.py`, `study.yml`, `results/` |
| `gallery.yml` | the gallery: site, recorded codes, private codes, extra fields, public target |
| `docs/` | the site; the Studies pages are generated |
| `.github/workflows/sync.yml` | the reusable sync of a private gallery into its public one |

Starting a gallery, adding a study and publishing are described in the
[guides](https://spokes3d.github.io/gallery-template/guides/new-gallery/).
