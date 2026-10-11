from packages import lsystem as ls

growth_iterations = input_int("Growth Iterations", default=5)
branch_angle = input_float("Branch Angle", default=35.0)
node_rotation = input_float("Node Rotation", default=137.507764)
step = input_float("Step", default=0.2)

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

output("Geometry", plant)
output("Leaf Points", ls.points(plant, marker="Leaf"))
