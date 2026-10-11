from packages import lsystem as ls

# Koch Curve example.
# Angle and Step are runtime inputs. The L-system iterations count is compile-time.

angle = input_float("Angle", default=60.0)
step = input_float("Step", default=0.08)

geo = ls.system(
    ls.axiom("F"),
    ls.rule("F", "F+F--F+F"),
    ls.iterations(4),
    ls.angle(angle),
    ls.step(step),
)

output("Geometry", geo)
