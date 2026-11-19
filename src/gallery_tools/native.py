"""Run the C, C++, Fortran or Julia program of a study from its ``study.py``.

A study in another language keeps its sources in its folder, next to ``study.py``, which stays
the entry point: ``simulate`` runs the program and reads what it wrote, ``plot`` draws the
figures in Python::

    from gallery_tools import native

    def simulate(preset="quick"):
        text = native.run("decay.f90", PRESETS[preset]["steps"])
        return {"data": np.loadtxt(io.StringIO(text))}

``run`` compiles C, C++ and Fortran sources (once: the executable is kept until a source or a
flag changes) and starts Julia scripts with ``julia``. The compiler is the first one found of
the language's list, or the one its environment variable names (``CC``, ``CXX``, ``FC``,
``JULIA``). The sources a page should show are listed under ``sources`` in ``study.yml``.
"""

from __future__ import annotations

import hashlib
import os
import shlex
import shutil
import subprocess
import tempfile
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from gallery_tools.config import GalleryError


class ToolchainError(GalleryError):
    """A compiler or an interpreter the study needs is not installed."""


@dataclass(frozen=True)
class Language:
    """A language ``run`` knows: its files, its compiler or interpreter and its flags.

    Attributes
    ----------
    name : str
        The name shown on the page.
    suffixes : tuple of str
        The file suffixes of its sources, in lower case.
    variable : str
        The environment variable that names the command (``CC``, ``FC``, ...).
    commands : tuple of str
        The commands tried in order when the variable is not set.
    flags : tuple of str
        The default flags of a build, or of the interpreter.
    libraries : tuple of str
        What is linked after the sources.
    compiled : bool
        Whether the sources are compiled into an executable.
    fence : str
        The language of its code blocks on the page.
    """

    name: str
    suffixes: tuple[str, ...]
    variable: str
    commands: tuple[str, ...]
    flags: tuple[str, ...] = ("-O2",)
    libraries: tuple[str, ...] = ()
    compiled: bool = True
    fence: str = "text"


LANGUAGES = {
    "c": Language(
        "C", (".c",), "CC", ("cc", "gcc", "clang"), libraries=("-lm",), fence="c"
    ),
    "cpp": Language(
        "C++", (".cpp", ".cc", ".cxx"), "CXX", ("c++", "g++", "clang++"), fence="cpp"
    ),
    "fortran": Language(
        "Fortran",
        (".f90", ".f95", ".f03", ".f08", ".f", ".for"),
        "FC",
        ("gfortran", "flang", "ifx"),
        fence="fortran",
    ),
    "julia": Language(
        "Julia",
        (".jl",),
        "JULIA",
        ("julia",),
        flags=("--startup-file=no",),
        compiled=False,
        fence="julia",
    ),
}

#: Files that are shown or passed along and never compiled on their own.
HEADERS = {".h": "c", ".hpp": "cpp", ".hh": "cpp", ".inc": "fortran"}
#: The code-block language of other files a study may list under ``sources``.
OTHER_FENCES = {
    ".py": "python",
    ".toml": "toml",
    ".yml": "yaml",
    ".yaml": "yaml",
    ".json": "json",
    ".sh": "bash",
    ".cmake": "cmake",
}


def language_of(path: str | Path) -> Language | None:
    """The language of a source file, None for a file ``run`` cannot run."""
    suffix = Path(path).suffix.lower()
    for language in LANGUAGES.values():
        if suffix in language.suffixes:
            return language
    return None


def fence_of(path: str | Path) -> str:
    """The code-block language of a file on the page."""
    path = Path(path)
    suffix = path.suffix.lower()
    language = language_of(path)
    if language:
        return language.fence
    if suffix in HEADERS:
        return LANGUAGES[HEADERS[suffix]].fence
    if path.name in ("Makefile", "makefile"):
        return "makefile"
    return OTHER_FENCES.get(suffix, "text")


def command(language: Language) -> list[str]:
    """The compiler or interpreter of ``language``, as the start of a command line."""
    named = os.environ.get(language.variable, "").strip()
    candidates = [shlex.split(named)] if named else [[c] for c in language.commands]
    for candidate in candidates:
        if shutil.which(candidate[0]):
            return candidate
    tried = named or ", ".join(language.commands)
    raise ToolchainError(
        f"no {language.name} {'compiler' if language.compiled else 'interpreter'} "
        f"found (tried {tried}); install one or set {language.variable}"
    )


def version(language: Language) -> str:
    """The first line of ``--version`` of the language's compiler or interpreter."""
    done = subprocess.run(
        [*command(language), "--version"], capture_output=True, text=True, check=False
    )
    lines = (done.stdout or done.stderr).strip().splitlines()
    return lines[0].strip() if lines else "unknown"


def toolchain(paths: Iterable[str | Path]) -> dict[str, str]:
    """The versions of the compilers and interpreters of ``paths``, by language name.

    A language whose compiler is not installed is left out: the record is of what ran.
    """
    out = {}
    for path in paths:
        language = language_of(path)
        if language and language.name not in out:
            try:
                out[language.name] = version(language)
            except ToolchainError:
                continue
    return out


def _check(done: subprocess.CompletedProcess, what: str) -> None:
    """Raise with the program's own messages when it failed."""
    if done.returncode:
        raise GalleryError(
            f"{what} failed (exit {done.returncode}):\n{done.stderr or done.stdout}"
        )


def _split(
    sources: str | Path | Iterable[str | Path],
) -> tuple[Language, list[Path], list[Path]]:
    """The language of ``sources``, the files to compile or run and the headers."""
    if isinstance(sources, str | Path):
        sources = [sources]
    paths = [Path(s).resolve() for s in sources]
    for path in paths:
        if not path.is_file():
            raise GalleryError(f"no source file {path}")
    headers = [p for p in paths if p.suffix.lower() in HEADERS]
    units = [p for p in paths if p not in headers]
    languages = {language_of(p) for p in units}
    if len(languages) != 1 or None in languages:
        raise GalleryError(
            f"the sources {[p.name for p in paths]} must be of one language of "
            f"{[lang.name for lang in LANGUAGES.values()]}"
        )
    return languages.pop(), units, headers


def build(
    sources: str | Path | Iterable[str | Path], *, flags: Iterable[str] | None = None
) -> Path:
    """Compile C, C++ or Fortran sources; return the executable.

    The executable is kept in the temporary folder of the machine under a name made from the
    sources, the flags and the compiler, so a build is done again only when one of them changes.

    Parameters
    ----------
    sources : path or list of paths
        The source files, in the order the compiler needs them (a Fortran module before the
        program that uses it). Headers may be listed: they are not compiled, but a change in
        one rebuilds.
    flags : list of str, optional
        The compiler flags, instead of the language's defaults (``-O2``).

    Returns
    -------
    Path
        The executable.
    """
    language, units, headers = _split(sources)
    if not language.compiled:
        raise GalleryError(f"{language.name} is not compiled: use run")
    compiler = command(language)
    flags = list(language.flags if flags is None else flags)
    digest = hashlib.sha256(repr((compiler, version(language), flags)).encode())
    for path in (*units, *headers):
        digest.update(path.name.encode() + b"\0" + path.read_bytes())
    folder = Path(tempfile.gettempdir()) / "gallery-native" / digest.hexdigest()[:20]
    executable = folder / units[-1].stem
    if not executable.exists():
        folder.mkdir(parents=True, exist_ok=True)
        includes = sorted({f"-I{p.parent}" for p in (*units, *headers)})
        done = subprocess.run(
            [
                *compiler,
                *flags,
                *includes,
                *map(str, units),
                "-o",
                str(executable),
                *language.libraries,
            ],
            cwd=folder,  # Fortran writes its .mod files where it runs
            capture_output=True,
            text=True,
            check=False,
        )
        _check(done, f"compiling {units[-1].name}")
    return executable


def run(
    sources: str | Path | Iterable[str | Path],
    *args: Any,
    flags: Iterable[str] | None = None,
    cwd: str | Path | None = None,
    env: Mapping[str, str] | None = None,
    stdin: str | None = None,
    timeout: float | None = None,
) -> str:
    """Compile (if the language needs it) and run a program; return what it printed.

    Parameters
    ----------
    sources : path or list of paths
        The source file or files, relative to the working directory (the builder and the
        tests run a study in its folder). For Julia, the script; its folder is the project
        when it holds a ``Project.toml``.
    *args
        The arguments of the program, turned into strings.
    flags : list of str, optional
        The compiler flags (or the flags of ``julia``), instead of the defaults.
    cwd : path, optional
        Where the program runs, and so where the files it writes land.
    env : mapping, optional
        Environment variables added for the run (``OMP_NUM_THREADS``, ...).
    stdin : str, optional
        Text the program reads from its standard input.
    timeout : float, optional
        Seconds after which the run is stopped.

    Returns
    -------
    str
        The standard output of the program.
    """
    language, units, _ = _split(sources)
    if language.compiled:
        line = [str(build(sources, flags=flags))]
    else:
        script = units[-1]
        options = list(language.flags if flags is None else flags)
        if (script.parent / "Project.toml").is_file():
            options.append(f"--project={script.parent}")
        line = [*command(language), *options, str(script)]
    done = subprocess.run(
        [*line, *map(str, args)],
        cwd=cwd,
        env={**os.environ, **env} if env else None,
        input=stdin,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    _check(done, f"running {units[-1].name}")
    return done.stdout
