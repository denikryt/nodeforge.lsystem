from packages import lsystem

# Dragon Curve example.
# Angle and Step are runtime inputs. The L-system iterations count is compile-time.

angle = input_float("Angle", default=90.0)
step = input_float("Step", default=0.04)

geo = generate_lsystem(
    axiom("FX"),
    rule("X", "X+YF+"),
    rule("Y", "-FX-Y"),
    iterations(10),
    lsystem.angle(angle),
    lsystem.step(step),
)

output("Geometry", geo)
