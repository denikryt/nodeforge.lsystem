from packages import lsystem as ls

# Dragon Curve example.
# Angle and Step are runtime inputs. The L-system iterations count is compile-time.

angle = input_float("Angle", default=90.0)
step = input_float("Step", default=0.04)

geo = ls.system(
    ls.axiom("FX"),
    ls.rule("X", "X+YF+"),
    ls.rule("Y", "-FX-Y"),
    ls.iterations(10),
    ls.angle(angle),
    ls.step(step),
)

output("Geometry", geo)
