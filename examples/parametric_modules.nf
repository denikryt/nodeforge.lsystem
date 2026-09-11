# Parameterized draw, move, and turn commands.

length = input_float("Length", default=2.0)
turn = input_float("Turn", default=90.0)

geo = ls_system(
    ls_axiom("F(length)+(turn)f(length)F(length)-(turn)F(length)"),
    ls_iterations(0),
    ls_angle(30.0),
    ls_step(1.0),
    ls_param("length", length),
    ls_param("turn", turn),
)

output("Geometry", geo)
