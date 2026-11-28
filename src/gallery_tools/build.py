"""Build the Studies pages of the site from the studies and their cached results.

The builder reads each study's docstring and ``study.yml`` without running it, gets the result
of its docs preset from the cache in ``studies/<stem>/results/`` (or runs it and fills the
cache), draws the figures with the script's ``plot`` function (as web figures where it can, see
``gallery_tools.figures``) and writes a page led by the figures: the first paragraph of the
description, the figures with their captions, the status, the set-up (``setup`` of the script),
the rest of the description, an optional table or the printed output, the profile of the run,
the details, how to run it and the complete source. It also writes the listing, a gallery of cards (the theme's ``GalleryGrid``)
with each study's front figure (``front_figure`` of ``study.yml``, the first by default), and one
page per code and per kind that shows the studies using that code or of that kind the same way.

A simulation is run only when there is no cached result for its preset, or when it is asked for
with ``rerun``; a long run is therefore done once, by hand, and its result is committed. The run
is profiled with scope-profiler, with the regions of every library on, and the longest regions
are kept with the result.
"""

from __future__ import annotations

import contextlib
import datetime
import io
import json
import os
import pickle
import runpy
import shlex
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from importlib import metadata
from pathlib import Path
from typing import Any

import scope_profiler as sp

from gallery_tools import figures as web_figures
from gallery_tools import native
from gallery_tools.config import TOOLS, Gallery, GalleryError
from gallery_tools.study import KINDS, Study, discover, distribution_name, module_name

#: The number of regions of a run's profile kept with its result.
PROFILE_REGIONS = 15


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


def profiled(study: Study, simulate: Callable[[], Any]) -> tuple[Any, list[dict]]:
    """Run ``simulate`` in a scope-profiler session with the regions of every library on.

    Returns the result and the ``PROFILE_REGIONS`` longest regions, each with its number of
    calls and its total and mean time in seconds. The run is not profiled, and the regions are
    empty, when a session is open already or with ``profile: false`` in ``study.yml`` (for a
    study that opens its own session, such as a picnic run with ``profiling=``: sessions do
    not nest).
    """
    if study.meta.get("profile") is False or sp.is_configured():
        return simulate(), []
    try:
        with sp.session(
            output=None, enable_tags=["*"], verbose=False, suppress_notes=True
        ):
            result = simulate()
            timings = sp.current_timings()
    finally:
        sp.reset()  # a finished session stays configured: the next study needs a fresh one
    regions = [
        {
            "region": name,
            "calls": int(t["num_calls"]),
            "total": float(f"{t['total']:.4g}"),
            "mean": float(f"{t['mean']:.4g}"),
        }
        for name, t in timings.items()
    ]
    regions.sort(key=lambda r: -r["total"])
    return result, regions[:PROFILE_REGIONS]


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
        result, regions = profiled(study, lambda: namespace["simulate"](preset))
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
    if regions:
        meta["profile"] = regions
    compilers = native.toolchain(study.sources)
    if compilers:
        meta["toolchain"] = compilers
    result_file.parent.mkdir(exist_ok=True)
    result_file.write_bytes(pickle.dumps(result, protocol=4))
    meta_file.write_text(json.dumps(meta, indent=2) + "\n")
    return result, meta


def source_fence(code: str, language: str = "python") -> str:
    """Wrap the complete source without truncating long scripts."""
    ticks = "```"
    while ticks in code:
        ticks += "`"
    return f"{ticks}{language}\n{code.rstrip()}\n{ticks}"


def other_sources(study: Study) -> list[str]:
    """The sections of the sources in other languages (``sources`` of ``study.yml``)."""
    lines = []
    for path in study.sources:
        header = native.HEADERS.get(path.suffix.lower())
        language = native.language_of(path) or native.LANGUAGES.get(header)
        name = path.relative_to(study.folder).as_posix()
        title = f"{language.name} source" if language else "Source"
        lines += [
            f"## {title}: `{name}`",
            "",
            source_fence(path.read_text(), native.fence_of(path)),
            "",
        ]
    return lines


def fmt_seconds(seconds: float) -> str:
    """A run time for people."""
    if seconds < 90:
        return f"{seconds:.0f} s"
    if seconds < 5400:
        return f"{seconds / 60:.0f} min"
    return f"{seconds / 3600:.1f} h"


def fmt_duration(seconds: float) -> str:
    """A duration of a profiled region, in the unit that suits it."""
    if seconds < 1e-3:
        return f"{seconds * 1e6:.3g} µs"
    if seconds < 1:
        return f"{seconds * 1e3:.3g} ms"
    return f"{seconds:.3g} s"


def profile_part(meta: dict[str, Any]) -> list[str]:
    """The section of the run's profile: its longest regions (empty without a profile)."""
    regions = meta.get("profile") or []
    if not regions:
        return []
    wall = meta.get("wall_seconds") or 0
    rows = [
        f"| `{r['region']}` | {r['calls']} | {fmt_duration(r['total'])} "
        f"| {fmt_duration(r['mean'])} | "
        + (f"{100 * r['total'] / wall:.0f}%" if wall else "")
        + " |"
        for r in regions
    ]
    return [
        "## Profile",
        "",
        "The longest regions of the run, from scope-profiler with the regions of every "
        "library on. Regions can nest, so their times overlap.",
        "",
        "| Region | Calls | Total | Mean | Of the run |",
        "|---|---|---|---|---|",
        *rows,
        "",
    ]


def setup_part(study: Study, namespace: dict[str, Any], preset: str) -> list[str]:
    """The section of the set-up, from the script's optional ``setup(preset)``.

    ``setup`` returns the set-up of the preset as a mapping, label to value (model, domain,
    grid, time step, ...), without running the simulation.
    """
    if "setup" not in namespace:
        return []
    previous = Path.cwd()
    try:
        os.chdir(study.folder)
        rows = namespace["setup"](preset)
    finally:
        os.chdir(previous)
    if not isinstance(rows, dict):
        raise GalleryError(
            f"{study.stem}: setup({preset!r}) must return a mapping, label to value"
        )
    return [
        "## Set-up",
        "",
        "| | |",
        "|---|---|",
        *[f"| {label} | {value} |" for label, value in rows.items()],
        "",
    ]


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


def requirements(site: Site, study: Study, meta: dict[str, Any]) -> list[str]:
    """What ``pip install`` needs for the study: the recorded versions where they are released.

    The codes of the study and the distributions of its imports; a code recorded with a git
    commit (an editable or git install) is not pinned, since its version need not be released.
    The private codes of the gallery are left out (``run_part`` says so).
    """
    names = {distribution_name(c) for c in [*site.gallery.codes, *study.codes]}
    names |= {distribution_name(m) for m in study.third_party()}
    private = {module_name(c) for c in site.gallery.private_codes}
    recorded = {distribution_name(k): v for k, v in meta.get("codes", {}).items()}
    out = []
    for name in sorted(names, key=str.lower):
        if module_name(name) in private:
            continue
        if module_name(name) == "gallery_tools":
            out.append(TOOLS)
            continue
        entry = recorded.get(name, {})
        pinned = entry.get("version") and not entry.get("commit")
        out.append(f"{name}=={entry['version']}" if pinned else name)
    return out


def run_part(
    site: Site, study: Study, meta: dict[str, Any], preset: str, output: Path
) -> list[str]:
    """The section on running the study: install, run, and the files to download.

    Copies ``study.py`` and its other sources into ``output``, the folder of the page's files.
    """
    files = [study.source, *study.sources]
    links = []
    for path in files:
        name = path.relative_to(study.folder).as_posix()
        target = output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
        links.append(f"[{name}]({site.base}/studies/{study.slug}/{name})")
    install = " ".join(shlex.quote(r) for r in requirements(site, study, meta))
    command = "python study.py"
    if "--preset" in study.code:
        command += f" --preset {preset}"
    private = sorted(
        c
        for c in {*study.codes, *map(distribution_name, study.third_party())}
        if module_name(c) in {module_name(p) for p in site.gallery.private_codes}
    )
    lines = [
        "## Run it",
        "",
        "Download "
        + (
            " and ".join(links)
            if len(links) < 3
            else ", ".join(links[:-1]) + " and " + links[-1]
        )
        + (" into one folder" if len(links) > 1 else "")
        + ", then:",
        "",
        "```bash",
        *([f"pip install {install}"] if install else []),
        command,
        "```",
        "",
        f"The `{preset}` preset took "
        + (
            fmt_seconds(meta["wall_seconds"])
            if meta["wall_seconds"] >= 1
            else "under a second"
        )
        + " for the result shown here.",
    ]
    if "smoke" in study.presets and "--preset" in study.code and preset != "smoke":
        lines[-1] += " `--preset smoke` checks the set-up in seconds."
    if private:
        lines += [
            "",
            f"It needs {', '.join(private)}, which "
            + ("is" if len(private) == 1 else "are")
            + " not public: this page shows the cached result.",
        ]
    return [*lines, ""]


PLOTLY_FIGURE = "import PlotlyFigure from '@max-models/starlight-theme/components/PlotlyFigure.astro';"


def figure_tag(site: Site, study: Study, written: web_figures.Written, alt: str) -> str:
    """The figure on the page: an interactive web figure, else its picture."""
    url = f"/studies/{study.slug}"
    if written.web:
        attributes = [f'src="{url}/{written.web}"']
        attributes += [f'{k}="{url}/{v}"' for k, v in written.posters.items()]
        attributes.append(f"alt={json.dumps(alt)}")
        return f"<PlotlyFigure {' '.join(attributes)} />"
    return f"![{alt}]({site.base}{url}/{written.picture})"


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
    intro, _, rest = study.description.partition("\n\n")
    figures_part: list[str] = []
    results_part: list[str] = []
    setup_lines: list[str] = []
    profile_lines: list[str] = []
    run_lines: list[str] = []
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
                returned = namespace["plot"](result)
                table = namespace["table"](result) if "table" in namespace else ""
        finally:
            os.chdir(previous)
        figures = web_figures.collect(returned)
        if figures and study.front_figure > len(figures):
            raise GalleryError(
                f"{study.stem}: front_figure {study.front_figure}, but plot draws "
                f"{len(figures)} figures"
            )
        output.mkdir(parents=True)
        for index, (figure, caption) in enumerate(
            zip(figures, study.captions(figures), strict=True), start=1
        ):
            alt = f"{study.title}, figure {index}"
            written = web_figures.write(figure, output / f"plot-{index}", alt)
            text = sanitize_markdown(caption) if caption else ""
            figures_part += [
                figure_tag(site, study, written, alt),
                "",
                f"**Figure {index}.** {text}".rstrip(),
                "",
            ]
        plt.close("all")
        setup_lines = setup_part(study, namespace, preset)
        profile_lines = profile_part(meta)
        run_lines = run_part(site, study, meta, preset, output)
        presets = ", ".join(f"`{p}`" for p in study.presets)
        rows += [
            ("Preset shown", f"`{preset}` (of {presets})"),
            ("Run time of the result", fmt_seconds(meta["wall_seconds"])),
            ("Run on", meta["ran_at"][:10]),
            ("Versions", site.versions(study, meta)),
        ]
        if meta.get("toolchain"):
            compilers = "; ".join(f"{k}: {v}" for k, v in meta["toolchain"].items())
            rows.append(("Compilers", compilers))
        if table:
            results_part += ["## Comparison", "", table, ""]
        text = printed.getvalue().strip()
        if text and not table:
            results_part += ["## Printed output", "", "```text", text, "```", ""]
    web = any("<PlotlyFigure" in line for line in figures_part)
    page = [
        "---",
        f"title: {json.dumps(study.title)}",
        f"description: {json.dumps(study.summary)}",
        "sidebar:",
        f"  order: {study.order}",
        "---",
        "",
        *([PLOTLY_FIGURE, ""] if web else []),
        sanitize_markdown(intro),
        "",
        *figures_part,
        f":::note[Status]\n{sanitize_markdown(str(meta_info['status']))}\n:::",
        "",
    ]
    if setup_lines:
        page += [sanitize_markdown("\n".join(setup_lines)), ""]
    if rest.strip():
        page += ["## The study", "", sanitize_markdown(rest.strip()), ""]
    page += [
        *results_part,
        *profile_lines,
        "## Details",
        "",
        "| | |",
        "|---|---|",
        *[f"| {k} | {v} |" for k, v in rows],
        "",
        *run_lines,
        "## Python source",
        "",
        source_fence(study.code),
        "",
        *other_sources(study),
    ]
    site.studies.mkdir(parents=True, exist_ok=True)
    (site.studies / f"{study.slug}.mdx").write_text("\n".join(page))
    print(f"[studies] {study.stem} -> {site.studies / study.slug}.mdx")


GALLERY_GRID = "import GalleryGrid from '@max-models/starlight-theme/components/GalleryGrid.astro';"


def thumbnail(site: Site, study: Study) -> dict[str, str] | None:
    """The front figure of a study for its card: the web figure, else its picture."""
    folder = site.public / study.slug
    stem = f"plot-{study.front_figure}"
    for name, kind in ((f"{stem}.plotly.json", "plotly"), (f"{stem}.png", "png")):
        if (folder / name).exists():
            return {"kind": kind, "src": f"/studies/{study.slug}/{name}"}
    return None


def card(site: Site, study: Study) -> dict[str, Any]:
    """The card of a study in the gallery (an item of the theme's ``GalleryGrid``)."""
    kind = KINDS.get(study.kind, study.kind)
    codes = ", ".join(site.all_codes(study)) or "no codes"
    return {
        "title": study.title,
        "summary": f"{kind} · {codes}. {study.summary}",
        "href": f"/studies/{study.slug}/",
        "group": str(study.meta.get("category", "Other")),
        "thumbnail": thumbnail(site, study),
        "placeholder": "in development" if study.stub else "no figure",
    }


def listing(site: Site, studies: list[Study]) -> list[str]:
    """A gallery of the studies: a card each with its front figure, grouped by category."""
    items = json.dumps([card(site, s) for s in studies], ensure_ascii=False)
    # braces in the JSON are inside the expression, so MDX reads them as code
    return [
        f'<GalleryGrid items={{{items}}} filterLabel="Filter studies…" />',
        "",
    ]


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
        "the status box under the figures."
    )
    lines = [
        "---",
        "title: Studies",
        f"description: {json.dumps(gallery.description or 'The studies of the gallery.')}",
        "sidebar:",
        "  order: 0",
        "---",
        "",
        GALLERY_GRID,
        "",
        sanitize_markdown(text),
        "",
        *filters,
        *listing(site, studies),
    ]
    site.studies.mkdir(parents=True, exist_ok=True)
    (site.studies / "index.md").unlink(missing_ok=True)  # the listing of older builds
    (site.studies / "index.mdx").write_text("\n".join(lines))
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
                GALLERY_GRID,
                "",
                f"{lead} [All studies]({site.base}/studies/).",
                "",
                *listing(site, members),
            ]
            (target / f"{slugify(key)}.mdx").write_text("\n".join(page))


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
