from packages import lsystem as ls

# Parameterized draw, move, and turn commands.

def parametric_modules(
    segment_length: Float['Length'] = 2.0,
    turn: Float['Turn'] = 90.0,
) -> Geometry['Geometry']:
    geo = ls.system(
        ls.axiom("F(length)+(turn)f(length)F(length)-(turn)F(length)"),
        ls.iterations(0),
        ls.angle(30.0),
        ls.step(1.0),
        ls.param("length", segment_length),
        ls.param("turn", turn),
    )

    return geo
