r"""Leapfrog energy error.

The example of a study in another language: the program `oscillator.c` integrates the harmonic
oscillator $\ddot x = -x$ with the explicit Euler, the symplectic Euler and the leapfrog
method, and this script compiles it, runs it and plots what it prints
(`gallery_tools.native.run`). The energy of the explicit Euler method grows without bound,
while the two symplectic methods keep it within a band, of width $O(h)$ and $O(h^2)$.

Compared: the energy error of the three methods over the same periods.

Not compared: the phase error, which all three methods have.
"""

import argparse
import io

import matplotlib.pyplot as plt
import numpy as np

from gallery_tools import native

PRESETS = {
    "smoke": {"per_period": 20, "periods": 2},
    "full": {"per_period": 50, "periods": 20},
}
METHODS = ["explicit Euler", "symplectic Euler", "leapfrog"]


def simulate(preset: str = "full") -> dict:
    """Run the C program; return the time and the energy error of each method."""
    sizes = PRESETS[preset]
    printed = native.run("oscillator.c", sizes["per_period"], sizes["periods"])
    data = np.loadtxt(io.StringIO(printed))
    return {
        "periods": data[:, 0] / (2 * np.pi),
        "errors": {name: data[:, i + 1] for i, name in enumerate(METHODS)},
    }


def plot(result: dict) -> None:
    """The size of the energy error against time."""
    fig, ax = plt.subplots(figsize=(5, 3.5))
    for name, error in result["errors"].items():
        ax.semilogy(result["periods"], np.abs(error) + 1e-18, label=name)
    ax.set_xlabel("time in periods")
    ax.set_ylabel("energy error $|E - E_0|$")
    ax.legend()
    fig.tight_layout()


def table(result: dict) -> str:
    """The largest energy error of each method."""
    rows = [
        f"| {name} | {np.abs(error).max():.2e} |"
        for name, error in result["errors"].items()
    ]
    return "\n".join(["| Method | Largest energy error |", "|---|---|", *rows])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--preset", choices=sorted(PRESETS), default="full")
    args = parser.parse_args()
    result = simulate(args.preset)
    print(table(result))
    plot(result)
    plt.show()
