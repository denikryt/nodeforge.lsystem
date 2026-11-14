from packages import lsystem as ls, math

def fractal_plant(
    angle: Float['Angle'] = 25.0,
    step: Float['Step'] = 0.04,
) -> Geometry['Geometry']:
    geo = ls.system(
        ls.axiom("X"),
        ls.rule("X", "F+[[X]-X]-F[-FX]+X"),
        ls.rule("F", "FF"),
        ls.iterations(5),
        ls.angle(angle),
        ls.step(step),
    )

    geo = transform(geo, rotation=vector(0, 0, math.radians(90)))
    return geo
