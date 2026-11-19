/* The harmonic oscillator x'' = -x from x = 1, v = 0, with three integrators.
 *
 * Usage: oscillator <steps per period> <periods>
 * Prints one line per step: t, then the energy error E - E0 of the explicit Euler, the
 * symplectic Euler and the leapfrog method.
 */
#include <math.h>
#include <stdio.h>
#include <stdlib.h>

static double energy(double x, double v) { return 0.5 * (x * x + v * v); }

int main(int argc, char **argv) {
  if (argc != 3) {
    fprintf(stderr, "usage: %s <steps per period> <periods>\n", argv[0]);
    return 1;
  }
  const int per_period = atoi(argv[1]);
  const int periods = atoi(argv[2]);
  const double h = 2.0 * acos(-1.0) / per_period;
  const double e0 = energy(1.0, 0.0);
  double xe = 1.0, ve = 0.0; /* explicit Euler */
  double xs = 1.0, vs = 0.0; /* symplectic Euler */
  double xl = 1.0, vl = 0.0; /* leapfrog (kick-drift-kick) */

  for (int n = 1; n <= per_period * periods; n++) {
    const double x_old = xe;
    xe += h * ve;
    ve -= h * x_old;

    vs -= h * xs;
    xs += h * vs;

    vl -= 0.5 * h * xl;
    xl += h * vl;
    vl -= 0.5 * h * xl;

    printf("%.17g %.17g %.17g %.17g\n", n * h, energy(xe, ve) - e0,
           energy(xs, vs) - e0, energy(xl, vl) - e0);
  }
  return 0;
}
