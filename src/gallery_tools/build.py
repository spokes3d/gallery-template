"""Build the Studies pages of the site from the studies and their cached results.

The builder reads each study's docstring and ``study.yml`` without running it, gets the result
of its docs preset from the cache in ``studies/<stem>/results/`` (or runs it and fills the
cache), draws the figures with the script's ``plot`` function and writes a page with the
description, the status, the complete source, the printed output, an optional table and the
figures. It also writes the listing, and one page per code and per kind that lists the studies
using that code or of that kind.

A simulation is run only when there is no cached result for its preset, or when it is asked for
with ``rerun``; a long run is therefore done once, by hand, and its result is committed.
"""

from __future__ import annotations

import contextlib
import datetime
import io
import json
import os
import pickle
import runpy
import shutil
import subprocess
import sys
import time
from importlib import metadata
from pathlib import Path
from typing import Any

from gallery_tools.config import Gallery, GalleryError
from gallery_tools.study import KINDS, Study, discover


def sanitize_markdown(text: str) -> str:
    """Make Markdown valid MDX, keeping code and math (the theme's notebook tool)."""
    try:
        from notebooks import sanitize_markdown as theme_sanitize
    except ImportError:  # before `npm ci`: escape what MDX reads as JSX
        return text.replace("{", "\\{").replace("<", "&lt;")
    return theme_sanitize(text)


def _git(path: Path) -> str:
    """The short commit of the repository at ``path``, with ``+dirty`` for uncommitted changes."""
    try:
        head = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "-C", str(path), "status", "--porcelain"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return head + ("+dirty" if dirty else "")


def provenance(codes: list[str]) -> dict[str, Any]:
    """Versions of the codes, and the git commit of editable or git installs."""
    out: dict[str, Any] = {}
    for name in codes:
        try:
            dist = metadata.distribution(name)
        except metadata.PackageNotFoundError:
            continue
        entry: dict[str, Any] = {"version": dist.version}
        direct = dist.read_text("direct_url.json")
        if direct:
            info = json.loads(direct)
            url = info.get("url", "")
            if url.startswith("file://"):
                entry["commit"] = _git(Path(url[7:]))
            elif "vcs_info" in info:
                entry["commit"] = info["vcs_info"].get("commit_id", "")[:10]
        out[name] = entry
    return out


def load_script(study: Study) -> dict[str, Any]:
    """Execute the script without its ``__main__`` block; return its namespace."""
    previous = Path.cwd()
    try:
        os.chdir(study.folder)
        return runpy.run_path(str(study.source), run_name="gallery_study")
    finally:
        os.chdir(previous)


def get_result(
    gallery: Gallery,
    study: Study,
    namespace: dict[str, Any],
    preset: str,
    *,
    rerun: bool = False,
    cached_only: bool = False,
) -> tuple[Any, dict[str, Any]]:
    """The result of ``preset`` from the cache, or run the simulation and fill the cache."""
    result_file, meta_file = study.cache(preset)
    if result_file.exists() and meta_file.exists() and not rerun:
        print(f"[studies] {study.stem}: cached {preset} result")
        return pickle.loads(result_file.read_bytes()), json.loads(meta_file.read_text())
    if cached_only:
        raise GalleryError(
            f"{study.stem}: no cached {preset!r} result and --cached-only given; "
            f"run `gallery build {study.stem} --rerun {study.stem}`"
        )
    print(f"[studies] {study.stem}: running preset {preset} ...")
    start = time.time()
    previous = Path.cwd()
    try:
        os.chdir(study.folder)
        result = namespace["simulate"](preset)
    finally:
        os.chdir(previous)
    seconds = time.time() - start
    meta = {
        "preset": preset,
        "wall_seconds": round(seconds, 1),
        "ran_at": datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds"),
        "python": sys.version.split()[0],
        "codes": provenance(sorted(set(gallery.codes) | set(study.codes))),
    }
    result_file.parent.mkdir(exist_ok=True)
    result_file.write_bytes(pickle.dumps(result, protocol=4))
    meta_file.write_text(json.dumps(meta, indent=2) + "\n")
    return result, meta


def source_fence(code: str) -> str:
    """Wrap the complete source without truncating long scripts."""
    ticks = "```"
    while ticks in code:
        ticks += "`"
    return f"{ticks}python\n{code.rstrip()}\n{ticks}"


def fmt_seconds(seconds: float) -> str:
    """A run time for people."""
    if seconds < 90:
        return f"{seconds:.0f} s"
    if seconds < 5400:
        return f"{seconds / 60:.0f} min"
    return f"{seconds / 3600:.1f} h"


def slugify(name: str) -> str:
    """A URL segment for a code or a kind."""
    return "".join(c if c.isalnum() else "-" for c in name.lower()).strip("-")


class Site:
    """Where the pages go and how they link."""

    def __init__(self, gallery: Gallery) -> None:
        self.gallery = gallery
        self.base = gallery.base
        self.content = gallery.content
        self.studies = gallery.content / "studies"
        self.public = gallery.docs / "public" / "studies"
        theme = gallery.docs / "node_modules" / "@max-models" / "starlight-theme"
        if (theme / "tools").is_dir() and str(theme / "tools") not in sys.path:
            sys.path.insert(0, str(theme / "tools"))

    def study_link(self, study: Study) -> str:
        """The link to a study's page."""
        return f"{self.base}/studies/{study.slug}/"

    def code_link(self, code: str) -> str:
        """The link to the listing of the studies that use ``code``."""
        return f"[{code}]({self.base}/by-code/{slugify(code)}/)"

    def kind_link(self, kind: str) -> str:
        """The link to the listing of the studies of ``kind``."""
        return f"[{KINDS.get(kind, kind)}]({self.base}/by-kind/{slugify(kind)}/)"

    def all_codes(self, study: Study) -> list[str]:
        """The codes of a study, the Python ones and the external ones."""
        return study.codes + list((study.meta.get("external_codes") or {}).keys())

    def versions(self, study: Study, meta: dict[str, Any]) -> str:
        """The versions and commits of the codes a study uses."""
        parts = []
        for name in study.codes:
            entry = meta.get("codes", {}).get(name)
            if entry:
                commit = f" @ {entry['commit']}" if entry.get("commit") else ""
                parts.append(f"{name} {entry['version']}{commit}")
        for name, version in (study.meta.get("external_codes") or {}).items():
            parts.append(f"{name} {version}")
        return ", ".join(parts) or "not recorded"

    def field_rows(self, study: Study) -> list[tuple[str, str]]:
        """The rows of the gallery's extra fields."""
        rows = []
        for key, spec in self.gallery.fields.items():
            value = study.meta.get(key, spec.get("default"))
            if value is None or value == []:
                value = spec.get("default", "")
            if isinstance(value, list):
                value = ", ".join(str(v) for v in value) or spec.get("default", "")
            text = str(value)
            if spec.get("link"):
                text += (
                    f" ([{spec.get('link_text', 'about')}]({self.base}{spec['link']}))"
                )
            rows.append((spec.get("label", key), text))
        return rows


def build_study(
    site: Site,
    study: Study,
    *,
    preset: str | None = None,
    rerun: bool = False,
    cached_only: bool = False,
) -> None:
    """Write the page of one study and its figures."""
    gallery = site.gallery
    meta_info = study.meta
    preset = preset or study.preset
    output = site.public / study.slug
    shutil.rmtree(output, ignore_errors=True)
    codes = site.all_codes(study)
    rows = [
        ("Kind", site.kind_link(study.kind)),
        ("Codes", ", ".join(site.code_link(c) for c in codes) or "none"),
        *site.field_rows(study),
    ]
    if meta_info.get("preprint"):
        rows.append(("Preprint", str(meta_info["preprint"])))
    body: list[str] = []
    if study.stub:
        rows.append(("State", "in development, not run"))
    else:
        namespace = load_script(study)
        result, meta = get_result(
            gallery, study, namespace, preset, rerun=rerun, cached_only=cached_only
        )
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        plt.close("all")
        printed = io.StringIO()
        previous = Path.cwd()
        try:
            os.chdir(study.folder)
            with contextlib.redirect_stdout(printed):
                namespace["plot"](result)
                table = namespace["table"](result) if "table" in namespace else ""
        finally:
            os.chdir(previous)
        captions = meta_info.get("figures") or []
        output.mkdir(parents=True)
        plots = []
        for index, number in enumerate(plt.get_fignums(), start=1):
            filename = f"plot-{index}.png"
            plt.figure(number).savefig(output / filename, dpi=150, bbox_inches="tight")
            caption = captions[index - 1] if index <= len(captions) else f"Plot {index}"
            plots.append(
                f"![{study.title}: plot {index}]({site.base}/studies/{study.slug}/{filename})"
                f"\n\n*{sanitize_markdown(caption)}*"
            )
        plt.close("all")
        presets = ", ".join(f"`{p}`" for p in study.presets)
        rows += [
            ("Preset shown", f"`{preset}` (of {presets})"),
            ("Run time of the result", fmt_seconds(meta["wall_seconds"])),
            ("Run on", meta["ran_at"][:10]),
            ("Versions", site.versions(study, meta)),
        ]
        if table:
            body += ["## Comparison", "", table, ""]
        text = printed.getvalue().strip()
        if text and not table:
            body += ["## Printed output", "", "```text", text, "```", ""]
        body += [
            "## Plots",
            "",
            "\n\n".join(plots) or "This study does not draw figures.",
            "",
        ]
    page = [
        "---",
        f"title: {json.dumps(study.title)}",
        f"description: {json.dumps(study.summary)}",
        "sidebar:",
        f"  order: {study.order}",
        "---",
        "",
        "| | |",
        "|---|---|",
        *[f"| {k} | {v} |" for k, v in rows],
        "",
        f":::note[Status]\n{sanitize_markdown(str(meta_info['status']))}\n:::",
        "",
        sanitize_markdown(study.description),
        "",
        "## Python source",
        "",
        source_fence(study.code),
        "",
        *body,
    ]
    site.studies.mkdir(parents=True, exist_ok=True)
    (site.studies / f"{study.slug}.mdx").write_text("\n".join(page))
    print(f"[studies] {study.stem} -> {site.studies / study.slug}.mdx")


def listing(site: Site, studies: list[Study]) -> list[str]:
    """A table of studies, grouped by category."""
    lines: list[str] = []
    categories: dict[str, list[Study]] = {}
    for study in studies:
        categories.setdefault(str(study.meta.get("category", "Other")), []).append(
            study
        )
    for category, members in categories.items():
        lines += [
            f"## {category}",
            "",
            "| Study | Kind | Codes | State |",
            "|---|---|---|---|",
        ]
        for s in members:
            state = "in development" if s.stub else "has results"
            codes = ", ".join(site.code_link(c) for c in site.all_codes(s)) or "none"
            lines.append(
                f"| [{s.title}]({site.study_link(s)}) | {site.kind_link(s.kind)} | {codes} | {state} |"
            )
        lines.append("")
    return lines


def write_index(site: Site, studies: list[Study], intro: str = "") -> None:
    """The listing of all studies, the filters, and a page per code and per kind."""
    gallery = site.gallery
    codes = sorted({c for s in studies for c in site.all_codes(s)}, key=str.lower)
    kinds = [k for k in KINDS if any(s.kind == k for s in studies)]
    filters = [
        "**By kind:** " + " · ".join(site.kind_link(k) for k in kinds),
        "",
        "**By code:** " + " · ".join(site.code_link(c) for c in codes),
        "",
    ]
    text = intro or (
        "Each study is a complete script with its result cached, so that this site does not "
        "rerun long simulations. A study says what it verifies and what it does not: read "
        "the status box before the figures."
    )
    lines = [
        "---",
        "title: Studies",
        f"description: {json.dumps(gallery.description or 'The studies of the gallery.')}",
        "sidebar:",
        "  order: 0",
        "---",
        "",
        text,
        "",
        *filters,
        *listing(site, studies),
    ]
    site.studies.mkdir(parents=True, exist_ok=True)
    (site.studies / "index.md").write_text("\n".join(lines))
    for folder, keys, member, label in (
        ("by-code", codes, lambda s, c: c in site.all_codes(s), "use"),
        ("by-kind", kinds, lambda s, k: s.kind == k, "kind"),
    ):
        target = site.content / folder
        shutil.rmtree(target, ignore_errors=True)
        target.mkdir(parents=True)
        for key in keys:
            members = [s for s in studies if member(s, key)]
            if label == "use":
                title = f"Studies with {key}"
                lead = f"The studies that use {key}."
            else:
                title = f"{KINDS[key]} studies"
                lead = f"The studies of kind *{KINDS[key].lower()}*."
            page = [
                "---",
                f"title: {json.dumps(title)}",
                f"description: {json.dumps(lead)}",
                "---",
                "",
                f"{lead} [All studies]({site.base}/studies/).",
                "",
                *listing(site, members),
            ]
            (target / f"{slugify(key)}.md").write_text("\n".join(page))


def build(
    gallery: Gallery,
    stems: list[str] | None = None,
    *,
    rerun: list[str] | None = None,
    rerun_all: bool = False,
    cached_only: bool = False,
    preset: str | None = None,
) -> list[Study]:
    """Regenerate the Studies pages, their figures and the filter pages.

    Parameters
    ----------
    gallery : Gallery
        The gallery to build.
    stems : list of str, optional
        The studies to build; all by default (a full build starts clean).
    rerun : list of str, optional
        Studies whose simulation is run again and whose cache is refilled.
    rerun_all : bool
        Run every simulation again.
    cached_only : bool
        Never run a simulation: fail if a result is not cached (CI).
    preset : str, optional
        Build this preset instead of each study's docs preset.

    Returns
    -------
    list of Study
        The studies built.
    """
    site = Site(gallery)
    studies = discover(gallery)
    unknown = set(stems or []) - {s.stem for s in studies}
    if unknown:
        raise GalleryError(f"unknown studies: {sorted(unknown)}")
    if not stems:
        shutil.rmtree(site.studies, ignore_errors=True)
        shutil.rmtree(site.public, ignore_errors=True)
    selected = [s for s in studies if not stems or s.stem in stems]
    for study in selected:
        build_study(
            site,
            study,
            preset=preset,
            rerun=rerun_all or study.stem in (rerun or []),
            cached_only=cached_only,
        )
    intro_file = gallery.root / "docs" / "studies-intro.md"
    intro = intro_file.read_text().strip() if intro_file.exists() else ""
    write_index(site, studies, intro)
    return selected
