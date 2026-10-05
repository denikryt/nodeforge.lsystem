from packages import lsystem

growth_iterations = input_int("Growth Iterations", default=5)
branch_angle = input_float("Branch Angle", default=35.0)
node_rotation = input_float("Node Rotation", default=137.507764)
step = input_float("Step", default=0.2)

plant = generate_lsystem(
    axiom("A"),
    rule("A", "F[&(branch_angle)B]/(node_rotation)A"),
    rule("B", "FLeaf"),
    iterations(growth_iterations),
    angle(25.0),
    lsystem.step(step),
    param("branch_angle", branch_angle),
    param("node_rotation", node_rotation),
    marker("Leaf"),
)

output("Geometry", plant)
output("Leaf Points", lsystem.points(plant, marker="Leaf"))
