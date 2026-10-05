from packages import lsystem

# Koch Curve example.
# Angle and Step are runtime inputs. The L-system iterations count is compile-time.

angle = input_float("Angle", default=60.0)
step = input_float("Step", default=0.08)

geo = generate_lsystem(
    axiom("F"),
    rule("F", "F+F--F+F"),
    iterations(4),
    lsystem.angle(angle),
    lsystem.step(step),
)

output("Geometry", geo)
