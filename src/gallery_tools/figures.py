"""The figures of a study: what its ``plot`` draws, written for the page as web figures.

``plot(result)`` draws Matplotlib figures and leaves them open. It may also return figures: a
Matplotlib animation (``matplotlib.animation.FuncAnimation``), a Plotly figure, a plasma-plots
``PlotResult``, or a list of them. Each figure becomes a web figure (``plot-<n>.plotly.json``):
interactive on the page, in the site's colours, an animation with a slider and Play button.
plasma-plots converts Matplotlib figures and animations (the same conversion as its
``backend="plotly"``) and maxplotlib writes the JSON; pictures of the figure for light and dark
pages (``plot-<n>.png``, ``plot-<n>.dark.png``) are shown until it has loaded. Formulas in
labels become Unicode text (plasma-plots' default), which the pictures show as well.

Without plasma-plots, or when any part of a figure cannot be converted (the conversion is
strict: a figure is never published without one of its parts), a Matplotlib figure is written
as a picture, ``plot-<n>.png``, as before, with a warning in the build.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def _is_plotly(item: Any) -> bool:
    return type(item).__module__.startswith("plotly")


def _is_animation(item: Any) -> bool:
    from matplotlib.animation import Animation

    return isinstance(item, Animation)


def collect(returned: Any) -> list[Any]:
    """The figures of a study, in the order ``plot`` made them.

    Parameters
    ----------
    returned : object
        What ``plot`` returned: None, a figure, an animation, a ``PlotResult`` or a list of them.

    Returns
    -------
    list
        The open Matplotlib figures, an animation in place of its figure, then the Plotly
        figures ``plot`` returned.
    """
    import matplotlib.pyplot as plt

    if returned is None:
        items = []
    elif isinstance(returned, (list, tuple)):
        items = list(returned)
    else:
        items = [returned]
    # a plasma-plots PlotResult: its figure (a Matplotlib one is among the open figures)
    items = [item.fig if hasattr(item, "fit_results") else item for item in items]
    animations = {id(item._fig): item for item in items if _is_animation(item)}
    out = []
    for number in plt.get_fignums():
        figure = plt.figure(number)
        out.append(animations.pop(id(figure), figure))
    return out + [item for item in items if _is_plotly(item)]


def matplotlib_figure(item: Any):
    """The Matplotlib figure of a figure or an animation; None for a Plotly figure."""
    if _is_animation(item):
        return item._fig
    return None if _is_plotly(item) else item


def own_caption(item: Any) -> str | None:
    """The caption a figure carries, or None.

    ``fig.caption`` of a Matplotlib figure (plasma-plots ``figure(caption=...)``, maxplotlib
    ``Canvas(caption=...)``), or ``layout.meta["caption"]`` of a Plotly figure.
    """
    if _is_plotly(item):
        meta = item.layout.meta
        return meta.get("caption") if isinstance(meta, dict) else None
    return getattr(matplotlib_figure(item), "caption", None)


def to_plotly(item: Any):
    """The figure as a Plotly figure, converted by plasma-plots."""
    if _is_plotly(item):
        return item
    from plasma_plots.plotly_backend import animation_to_plotly
    from plasma_plots.plotly_backend import to_plotly as convert

    # strict: a figure with a part the conversion skips is not published without that part
    if _is_animation(item):
        return animation_to_plotly(item, strict=True)
    return convert(item, strict=True)


@dataclass
class Written:
    """The files of one figure, by their names in the study's folder of the site."""

    picture: str | None = None
    web: str | None = None
    posters: dict[str, str] = field(default_factory=dict)


def write(item: Any, stem: Path, alt: str) -> Written:
    """Write one figure: a web figure with its posters, else a picture.

    Parameters
    ----------
    item : object
        A Matplotlib figure, a Matplotlib animation or a Plotly figure.
    stem : Path
        The path of the files without the extension, e.g. ``.../plot-1``.
    alt : str
        A text alternative for the figure.
    """
    written = Written()
    figure = matplotlib_figure(item)
    if figure is not None:
        figure.savefig(stem.with_suffix(".png"), dpi=150, bbox_inches="tight")
        written.picture = stem.name + ".png"
    try:
        web = to_plotly(item)
        from plasma_plots.plotting import PlotResult

        PlotResult(web).save(f"{stem}.plotly.json", alt=alt)
    except ImportError:
        return written
    except Exception as error:  # noqa: BLE001  (a figure the conversion does not handle)
        warnings.warn(f"{stem.name}: written as a picture: {error}", stacklevel=2)
        return written
    written.web = stem.name + ".plotly.json"
    try:
        from plasma_plots.plotly_backend import save_posters

        for path in save_posters(web, stem):
            name = Path(path).name
            key = "posterDark" if name.endswith(".dark.png") else "poster"
            written.posters[key] = name
    except Exception as error:  # noqa: BLE001  (kaleido or its browser missing)
        warnings.warn(f"{stem.name}: no posters: {error}", stacklevel=2)
    if not written.posters and written.picture:
        written.posters["poster"] = written.picture
    return written
