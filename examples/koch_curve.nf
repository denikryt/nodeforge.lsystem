from packages import lsystem as ls

# Koch Curve example.
# Angle and Step are runtime inputs. The L-system iterations count is compile-time.

def koch_curve(
    angle: Float['Angle'] = 60.0,
    step: Float['Step'] = 0.08,
) -> Geometry['Geometry']:
    geo = ls.system(
        ls.axiom("F"),
        ls.rule("F", "F+F--F+F"),
        ls.iterations(4),
        ls.angle(angle),
        ls.step(step),
    )

    return geo
