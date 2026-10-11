from packages import lsystem as ls

# Parameterized draw, move, and turn commands.

length = input_float("Length", default=2.0)
turn = input_float("Turn", default=90.0)

geo = ls.system(
    ls.axiom("F(length)+(turn)f(length)F(length)-(turn)F(length)"),
    ls.iterations(0),
    ls.angle(30.0),
    ls.step(1.0),
    ls.param("length", length),
    ls.param("turn", turn),
)

output("Geometry", geo)
