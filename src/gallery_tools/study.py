"""A study: a folder ``studies/<nn>_<name>/`` with ``study.py``, ``study.yml`` and results.

The script ``study.py`` is standalone: its module docstring is the title (first line) and the
text of the page, ``PRESETS`` names its sizes, ``simulate(preset)`` returns a picklable result,
``plot(result)`` draws the figures and an optional ``table(result)`` returns a Markdown table.

``study.yml`` holds what the site and the publishing need, read without running the script.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path
from typing import Any

import yaml

from gallery_tools.config import Gallery, GalleryError

SCRIPT = "study.py"
META = "study.yml"

#: The kinds of study. Only ``result`` (novel results a paper will use) waits for a preprint
#: before it can be public.
KINDS = {
    "verification": "Verification",
    "method": "Method",
    "example": "Example",
    "benchmark": "Benchmark",
    "result": "Result",
}
REQUIRED = ("category", "kind", "public", "codes", "status")
OPTIONAL = (
    "title",
    "summary",
    "preprint",
    "external_codes",
    "docs_preset",
    "runtime",
    "stub",
    "figures",
    "exclude",
)


def module_name(distribution: str) -> str:
    """The import name of a distribution, by convention (``plasma-plots`` -> ``plasma_plots``)."""
    return distribution.replace("-", "_").lower()


def distribution_name(module: str) -> str:
    """The distribution of an import name, by convention (``plasma_plots`` -> ``plasma-plots``)."""
    return module.replace("_", "-").lower()


class Study:
    """What is known about a study without running it.

    Parameters
    ----------
    folder : Path
        The folder of the study, ``studies/<nn>_<name>/``.
    """

    def __init__(self, folder: Path) -> None:
        self.folder = folder
        self.stem = folder.name
        self.source = folder / SCRIPT
        match = re.match(r"^(\d+)[_-](.*)$", self.stem)
        self.order = int(match.group(1)) if match else 0
        self.slug = re.sub(
            r"[^a-z0-9]+", "-", (match.group(2) if match else self.stem).lower()
        ).strip("-")
        for name in (SCRIPT, META):
            if not (folder / name).is_file():
                raise GalleryError(f"{self.stem}: no {name}")
        self.code = self.source.read_text()
        self.tree = ast.parse(self.code, filename=str(self.source))
        docstring = ast.get_docstring(self.tree) or ""
        first, _, rest = docstring.partition("\n")
        self.meta: dict[str, Any] = yaml.safe_load((folder / META).read_text()) or {}
        self.title = str(self.meta.get("title") or first.strip().rstrip("."))
        self.description = rest.strip()
        self.has_docstring = bool(docstring)
        self.presets: list[str] = []
        for node in self.tree.body:
            if isinstance(node, ast.Assign) and len(node.targets) == 1:
                if getattr(node.targets[0], "id", None) == "PRESETS" and isinstance(
                    node.value, ast.Dict
                ):
                    self.presets = [ast.literal_eval(k) for k in node.value.keys]

    @property
    def stub(self) -> bool:
        """A study announced and not yet run."""
        return bool(self.meta.get("stub"))

    @property
    def public(self) -> bool:
        """Whether the study goes to the public gallery."""
        return self.meta.get("public") is True

    @property
    def kind(self) -> str:
        """The kind of study (see ``KINDS``)."""
        return str(self.meta.get("kind", ""))

    @property
    def codes(self) -> list[str]:
        """The codes the study uses (distribution names)."""
        return list(self.meta.get("codes") or [])

    @property
    def preset(self) -> str:
        """The preset the page shows."""
        return str(self.meta.get("docs_preset", "quick"))

    @property
    def summary(self) -> str:
        """One sentence for the listing and the page description."""
        if self.meta.get("summary"):
            return str(self.meta["summary"])
        first = self.description.split("\n\n", 1)[0].replace("\n", " ")
        return first.split(". ")[0] if first else self.title

    def cache(self, preset: str) -> tuple[Path, Path]:
        """The result file and the metadata file of ``preset``."""
        results = self.folder / "results"
        return results / f"{preset}.pkl", results / f"{preset}.json"

    def imports(self) -> set[str]:
        """The top-level modules the script imports."""
        names: set[str] = set()
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Import):
                names |= {alias.name.split(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                names.add(node.module.split(".")[0])
        return names

    def third_party(self) -> set[str]:
        """The imported modules that are neither standard library nor ``__future__``."""
        return {
            name
            for name in self.imports()
            if name not in sys.stdlib_module_names and name != "__future__"
        }

    def problems(self, gallery: Gallery) -> list[str]:
        """What is wrong with the study (empty when it is well formed)."""
        out = []
        if not self.has_docstring:
            out.append("study.py needs a module docstring (title, then the text)")
        for key in REQUIRED:
            if key not in self.meta:
                out.append(f"study.yml needs {key!r}")
        allowed = set(REQUIRED) | set(OPTIONAL) | set(gallery.fields)
        unknown = sorted(set(self.meta) - allowed)
        if unknown:
            out.append(
                f"study.yml: unknown keys {unknown} (gallery.yml `fields` declares extra ones)"
            )
        if self.kind and self.kind not in KINDS:
            out.append(f"kind {self.kind!r} is not one of {sorted(KINDS)}")
        if "public" in self.meta and not isinstance(self.meta["public"], bool):
            out.append("public must be true or false")
        if not isinstance(self.meta.get("codes", []), list):
            out.append("codes must be a list")
        if not self.stub:
            if "smoke" not in self.presets:
                out.append("PRESETS needs a 'smoke' preset (the test runs it)")
            if self.preset not in self.presets:
                out.append(
                    f"docs_preset {self.preset!r} is not in PRESETS {self.presets}"
                )
            if not isinstance(self.meta.get("figures"), list):
                out.append("study.yml needs `figures`, a caption per figure")
        return out

    def public_problems(self, gallery: Gallery, local_modules: set[str]) -> list[str]:
        """Why the study cannot go to the public gallery (empty when it can).

        Parameters
        ----------
        gallery : Gallery
            The gallery the study belongs to.
        local_modules : set of str
            Module names defined by files of the repository outside the study: a public study
            must not import them, since they are not copied.
        """
        out = []
        if self.kind == "result" and not self.meta.get("preprint"):
            out.append(
                "a study of kind 'result' needs its `preprint` before it is public"
            )
        private = {module_name(c) for c in gallery.private_codes}
        used = (self.third_party() | {module_name(c) for c in self.codes}) & private
        if used:
            out.append(f"uses private codes {sorted(used)}")
        own = {p.stem for p in self.folder.rglob("*.py")} | {
            p.name for p in self.folder.iterdir() if p.is_dir()
        }
        helpers = (self.imports() & local_modules) - own
        if helpers:
            out.append(
                f"imports modules of the repository that are not copied: {sorted(helpers)}"
            )
        if self.stub:
            out.append("a stub has no result to show")
        return out


def discover(gallery: Gallery) -> list[Study]:
    """The studies of the gallery, in order."""
    if not gallery.studies_dir.is_dir():
        return []
    folders = sorted(
        p
        for p in gallery.studies_dir.iterdir()
        if p.is_dir() and re.match(r"^\d+[_-]", p.name)
    )
    return [Study(p) for p in folders]


def local_modules(gallery: Gallery) -> set[str]:
    """The module names the repository's own Python files define, outside the site."""
    skip = {".venv", "node_modules", "docs", ".git", "src"}
    names = set()
    for path in gallery.root.rglob("*.py"):
        if skip & set(path.relative_to(gallery.root).parts):
            continue
        names.add(path.stem)
        names.add(path.parent.name)
    names.discard(gallery.root.name)
    return names - {"study", "studies", "tests", "results"}
