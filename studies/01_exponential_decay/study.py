r"""Exponential decay.

The example study of the template. The decay $\dot y = -\lambda y$, $y(0) = 1$, is integrated
to $t = 1$ with the explicit Euler, the midpoint and the classical Runge-Kutta method, at a
range of step sizes; the error at the end against the exact solution $e^{-\lambda t}$ gives
each method's order of convergence.

Compared: the measured orders against the theoretical ones (1, 2 and 4).

Not compared: stability at large steps, which the step sizes here stay clear of.
"""

import argparse

import matplotlib.pyplot as plt
import numpy as np

PRESETS = {
    "smoke": {"steps": [4, 8, 16]},
    "full": {"steps": [4, 8, 16, 32, 64, 128, 256, 512]},
}
RATE = 2.0


def euler(f, y, h):
    """One explicit Euler step."""
    return y + h * f(y)


def midpoint(f, y, h):
    """One explicit midpoint step."""
    return y + h * f(y + 0.5 * h * f(y))


def rk4(f, y, h):
    """One classical Runge-Kutta step."""
    k1 = f(y)
    k2 = f(y + 0.5 * h * k1)
    k3 = f(y + 0.5 * h * k2)
    k4 = f(y + h * k3)
    return y + h * (k1 + 2 * k2 + 2 * k3 + k4) / 6


METHODS = {"Euler": (euler, 1), "midpoint": (midpoint, 2), "RK4": (rk4, 4)}


def simulate(preset: str = "full") -> dict:
    """The error at t = 1 of each method at each number of steps."""
    steps = np.array(PRESETS[preset]["steps"])
    exact = np.exp(-RATE)
    errors = {}
    for name, (step, _) in METHODS.items():
        out = []
        for n in steps:
            y, h = 1.0, 1.0 / n
            for _ in range(n):
                y = step(lambda u: -RATE * u, y, h)
            out.append(abs(y - exact))
        errors[name] = np.array(out)
    return {"steps": steps, "errors": errors}


def orders(result: dict) -> dict:
    """The order of each method, from a fit of log(error) against log(h)."""
    h = 1.0 / result["steps"]
    return {
        name: float(np.polyfit(np.log(h), np.log(err), 1)[0])
        for name, err in result["errors"].items()
    }


def plot(result: dict) -> None:
    """The error against the step size, with the fitted orders."""
    h = 1.0 / result["steps"]
    fitted = orders(result)
    fig, ax = plt.subplots(figsize=(5, 3.5))
    for name, err in result["errors"].items():
        ax.loglog(h, err, "o-", label=f"{name} (order {fitted[name]:.2f})")
    ax.set_xlabel("step size $h$")
    ax.set_ylabel("error at $t = 1$")
    ax.legend()
    fig.tight_layout()


def table(result: dict) -> str:
    """The measured orders against the theoretical ones."""
    fitted = orders(result)
    rows = [
        f"| {name} | {order} | {fitted[name]:.3f} |"
        for name, (_, order) in METHODS.items()
    ]
    return "\n".join(["| Method | Theory | Measured |", "|---|---|---|", *rows])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--preset", choices=sorted(PRESETS), default="full")
    args = parser.parse_args()
    result = simulate(args.preset)
    print(table(result))
    plot(result)
    plt.show()
