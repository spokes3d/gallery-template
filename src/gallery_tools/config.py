"""The configuration of a gallery: ``gallery.yml`` at the root of its repository."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

CONFIG = "gallery.yml"


class GalleryError(Exception):
    """A gallery or one of its studies is not well formed."""


@dataclass
class Public:
    """Where the public studies go: the public repository and its site."""

    owner: str
    repo: str
    title: str
    description: str
    overlay: str = "public"
    tools: str = (
        "gallery-tools @ git+https://github.com/spokes3d/gallery-template@devel"
    )


@dataclass
class Gallery:
    """A gallery: its site, the codes it records and the extra fields of its studies.

    Attributes
    ----------
    root : Path
        The root of the repository (the folder of ``gallery.yml``).
    title, description : str
        The title and the description of the site.
    owner, repo : str
        The GitHub owner and repository; the site is served at ``/<repo>/``.
    codes : list of str
        The distributions whose versions and commits are recorded with each result.
    private_codes : list of str
        Codes in private repositories: a public study must not use them.
    fields : dict
        Extra keys of ``study.yml`` this gallery allows, each with a ``label`` (the row of the
        study's table), an optional ``link`` (a page of the site) and an optional ``default``.
    public : Public or None
        Where the public studies go; None for a gallery that is itself public.
    """

    root: Path
    title: str
    description: str
    owner: str
    repo: str
    codes: list[str] = field(default_factory=list)
    private_codes: list[str] = field(default_factory=list)
    fields: dict[str, dict[str, Any]] = field(default_factory=dict)
    public: Public | None = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def base(self) -> str:
        """The base path of the site (``/<repo>``)."""
        return f"/{self.repo}"

    @property
    def studies_dir(self) -> Path:
        """The folder of the studies."""
        return self.root / "studies"

    @property
    def docs(self) -> Path:
        """The folder of the site."""
        return self.root / "docs"

    @property
    def content(self) -> Path:
        """The folder of the site's pages."""
        return self.docs / "src" / "content" / "docs"


def find_root(start: Path | None = None) -> Path:
    """The nearest folder at or above ``start`` that holds ``gallery.yml``."""
    here = (start or Path.cwd()).resolve()
    for folder in (here, *here.parents):
        if (folder / CONFIG).is_file():
            return folder
    raise GalleryError(f"no {CONFIG} in {here} or above")


def load(root: Path | None = None) -> Gallery:
    """Read ``gallery.yml`` of the gallery at ``root`` (default: found from the cwd)."""
    root = find_root(root)
    raw = yaml.safe_load((root / CONFIG).read_text()) or {}
    site = raw.get("site", {})
    for key in ("title", "owner", "repo"):
        if key not in site:
            raise GalleryError(f"{CONFIG}: site.{key} is required")
    public = None
    if raw.get("public"):
        try:
            public = Public(**raw["public"])
        except TypeError as error:
            raise GalleryError(f"{CONFIG}: public: {error}") from None
    return Gallery(
        root=root,
        title=site["title"],
        description=site.get("description", ""),
        owner=site["owner"],
        repo=site["repo"],
        codes=list(raw.get("codes", [])),
        private_codes=list(raw.get("private_codes", [])),
        fields=dict(raw.get("fields", {})),
        public=public,
        raw=raw,
    )
