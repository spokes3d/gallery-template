---
title: Starting a gallery
description: A new gallery from the template, or an existing repository on the gallery tools.
---

## From the template

1. "Use this template" on GitHub, or copy the repository without its history.
2. Edit `gallery.yml`: the title, the owner and the repository of the site, the codes whose
   versions are recorded, the private codes and the extra fields of `study.yml`.
3. Edit `docs/astro.config.mjs` (`repo`, `owner`, `title`) and the home page.
4. Replace `studies/01_exponential_decay/` with your studies ([Adding a
   study](/gallery-template/guides/studies/)).
5. In `pyproject.toml`, rename the project, depend on the gallery tools instead of being them,
   and add the codes the studies use:

   ```toml
   dependencies = [
     "gallery-tools @ git+https://github.com/spokes3d/gallery-template@devel",
     "numpy",
   ]
   ```

6. Enable GitHub Pages (Settings, Pages, source "GitHub Actions"); the docs workflow deploys
   `devel`.

## Layout

```text
gallery.yml                 the gallery: site, codes, fields, where public studies go
studies/<nn>_<name>/
  study.py                  the standalone script: docstring, PRESETS, simulate, plot, table
  study.yml                 kind, public, codes, status, captions, ...
  results/<preset>.pkl      the cached result of the docs preset, and its .json metadata
  data/                     anything else the study reads (optional)
docs/                       the Astro + Starlight site (the Studies pages are generated)
tests/test_studies.py       from gallery_tools.testing import *
public/                     files copied into the public gallery (a private gallery only)
```

## Commands

```bash
uv sync --extra dev
uv run gallery check                       # study.yml of every study, and the public rules
uv run gallery list --public               # what the public gallery gets
uv run gallery build                       # the Studies pages, cache first
uv run gallery build <stem> --rerun <stem> # rerun one study, refill its cache
uv run gallery build --cached-only         # as in CI: never run a simulation
uv run pytest                              # every study in its smoke preset
cd docs && npm ci && npm run dev           # the site at http://localhost:4321/<repo>/
```
