from packages import lsystem

# Parameterized draw, move, and turn commands.

length = input_float("Length", default=2.0)
turn = input_float("Turn", default=90.0)

geo = generate_lsystem(
    axiom("F(length)+(turn)f(length)F(length)-(turn)F(length)"),
    iterations(0),
    angle(30.0),
    step(1.0),
    param("length", length),
    param("turn", turn),
)

output("Geometry", geo)
