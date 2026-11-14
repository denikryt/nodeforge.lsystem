from packages import lsystem as ls

# Dragon Curve example.
# Angle and Step are runtime inputs. The L-system iterations count is compile-time.

def dragon_curve(
    angle: Float['Angle'] = 90.0,
    step: Float['Step'] = 0.04,
) -> Geometry['Geometry']:
    geo = ls.system(
        ls.axiom("FX"),
        ls.rule("X", "X+YF+"),
        ls.rule("Y", "-FX-Y"),
        ls.iterations(10),
        ls.angle(angle),
        ls.step(step),
    )

    return geo
