"""The ``gallery`` command: check the studies, build the site, export the public gallery."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from gallery_tools.config import GalleryError, load


def _check(args: argparse.Namespace) -> int:
    """Check every study, and that the public ones can go public."""
    from gallery_tools.export import check_public
    from gallery_tools.study import discover

    gallery = load(args.root)
    failed = 0
    studies = discover(gallery)
    for study in studies:
        for problem in study.problems(gallery):
            print(f"{study.stem}: {problem}")
            failed += 1
    if gallery.public is not None:
        for stem, problems in check_public(gallery).items():
            for problem in problems:
                print(f"{stem} (public): {problem}")
                failed += 1
    public = sum(s.public for s in studies)
    print(f"{len(studies)} studies, {public} public, {failed} problems")
    return 1 if failed else 0


def _list(args: argparse.Namespace) -> int:
    """List the studies with their kind and whether they are public."""
    from gallery_tools.study import discover

    for study in discover(load(args.root)):
        if args.public and not study.public:
            continue
        flag = "public " if study.public else "private"
        print(f"{study.stem:40s} {flag} {study.kind:12s} {', '.join(study.codes)}")
    return 0


def _build(args: argparse.Namespace) -> int:
    """Build the Studies pages."""
    from gallery_tools.build import build

    build(
        load(args.root),
        args.stems,
        rerun=args.rerun or [],
        rerun_all=args.rerun == [],
        cached_only=args.cached_only,
        preset=args.preset,
    )
    return 0


def _export(args: argparse.Namespace) -> int:
    """Write the public gallery."""
    from gallery_tools.export import export

    studies = export(load(args.root), Path(args.target))
    print(f"exported {len(studies)} public studies to {args.target}")
    for study in studies:
        print(f"  {study.stem}")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Run the ``gallery`` command."""
    parser = argparse.ArgumentParser(prog="gallery", description=__doc__)
    parser.add_argument(
        "--root", type=Path, help="the gallery (default: found from the cwd)"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    check = sub.add_parser("check", help="check study.yml of every study")
    check.set_defaults(func=_check)

    listing = sub.add_parser("list", help="list the studies")
    listing.add_argument("--public", action="store_true", help="only the public ones")
    listing.set_defaults(func=_list)

    build = sub.add_parser("build", help="build the Studies pages (cache first)")
    build.add_argument("stems", nargs="*", help="studies to build (default: all)")
    build.add_argument(
        "--rerun",
        nargs="*",
        metavar="STEM",
        default=None,
        help="rerun these studies' simulations (all without a name)",
    )
    build.add_argument(
        "--cached-only",
        action="store_true",
        help="never run a simulation: fail if a result is not cached (CI)",
    )
    build.add_argument("--preset", help="build this preset instead of the docs preset")
    build.set_defaults(func=_build)

    export = sub.add_parser("export", help="write the public gallery into a folder")
    export.add_argument("target", help="the public repository (emptied, .git kept)")
    export.set_defaults(func=_export)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except GalleryError as error:
        print(f"gallery: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
