from packages import lsystem, math

angle = input_float("Angle", default=25.0)
step = input_float("Step", default=0.04)

geo = generate_lsystem(
    axiom("X"),
    rule("X", "F+[[X]-X]-F[-FX]+X"),
    rule("F", "FF"),
    iterations(5),
    lsystem.angle(angle),
    lsystem.step(step),
)

geo = transform(geo, rotation=vector(0, 0, math.radians(90)))
output("Geometry", geo)