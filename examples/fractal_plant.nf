from packages import lsystem as ls, math

angle = input_float("Angle", default=25.0)
step = input_float("Step", default=0.04)

geo = ls.system(
    ls.axiom("X"),
    ls.rule("X", "F+[[X]-X]-F[-FX]+X"),
    ls.rule("F", "FF"),
    ls.iterations(5),
    ls.angle(angle),
    ls.step(step),
)

geo = transform(geo, rotation=vector(0, 0, math.radians(90)))
output("Geometry", geo)