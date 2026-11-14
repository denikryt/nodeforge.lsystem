from packages import lsystem as ls

def spatial_plant(
    growth_iterations: Int['Growth Iterations'] = 5,
    branch_angle: Float['Branch Angle'] = 35.0,
    node_rotation: Float['Node Rotation'] = 137.507764,
    step: Float['Step'] = 0.2,
):
    plant = ls.system(
        ls.axiom("A"),
        ls.rule("A", "F[&(branch_angle)B]/(node_rotation)A"),
        ls.rule("B", "FLeaf"),
        ls.iterations(growth_iterations),
        ls.angle(25.0),
        ls.step(step),
        ls.param("branch_angle", branch_angle),
        ls.param("node_rotation", node_rotation),
        ls.marker("Leaf"),
    )

    geometry = plant
    leaf_points = ls.points(plant, marker="Leaf")
    return geometry, leaf_points
