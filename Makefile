# Development environment (uv) and the documentation site (docs/, Astro + Starlight).
PYTHON ?= .venv/bin/python
# Studies to rerun: make docs-studies RERUN="01_exponential_decay"; RERUN=all reruns every study.
RERUN ?=
RERUN_FLAGS = $(if $(filter all,$(RERUN)),--rerun,$(if $(RERUN),$(RERUN) --rerun $(RERUN),))

.PHONY: help install test lint docs-install docs-studies docs-dev docs-build docs-preview docs-clean

help:  ## list the targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-16s %s\n", $$1, $$2}'

install:  ## uv sync with the dev extra, and the pre-commit hooks
	uv sync --extra dev
	uv run pre-commit install

test:  ## the checks, the tools' tests and every study in its smoke preset
	uv run gallery check
	uv run pytest --cov=gallery_tools --cov-report=term-missing

lint:  ## ruff and ssort
	uv run ruff check .
	uv run ruff format --check .
	uvx ssort --check --diff .

docs-install:  ## the npm packages of the site
	cd docs && npm ci

docs-studies:  ## the Studies pages (cached; RERUN=<stem> runs one)
	$(PYTHON) -m gallery_tools.cli build $(RERUN_FLAGS)

docs-dev:  ## live preview at http://localhost:4321/gallery-template/
	$(PYTHON) -m gallery_tools.cli build
	cd docs && DOCS_VALIDATE_LINKS=false npm run dev

docs-build:  ## the static site in docs/dist, as in CI (never runs a simulation)
	$(PYTHON) -m gallery_tools.cli build --cached-only
	cd docs && npm run check:mdx && DOCS_PYTHON=../$(PYTHON) npm run build

docs-preview:  ## serve docs/dist
	cd docs && npm run preview

docs-clean:  ## remove generated pages, figures and build output
	rm -rf docs/src/content/docs/studies docs/src/content/docs/by-code docs/src/content/docs/by-kind
	rm -rf docs/public/studies docs/dist docs/.astro
