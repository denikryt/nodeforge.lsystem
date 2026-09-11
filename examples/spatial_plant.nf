growth_iterations = input_int("Growth Iterations", default=5)
branch_angle = input_float("Branch Angle", default=35.0)
node_rotation = input_float("Node Rotation", default=137.507764)
step = input_float("Step", default=0.2)

plant = ls_system(
    ls_axiom("A"),
    ls_rule("A", "F[&(branch_angle)B]/(node_rotation)A"),
    ls_rule("B", "FLeaf"),
    ls_iterations(growth_iterations),
    ls_angle(25.0),
    ls_step(step),
    ls_param("branch_angle", branch_angle),
    ls_param("node_rotation", node_rotation),
    ls_marker("Leaf"),
)

output("Geometry", plant)
output("Leaf Points", ls_points(plant, marker="Leaf"))
