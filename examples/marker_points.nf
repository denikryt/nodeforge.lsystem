# Marker extraction and marker parameters.

size = input_float("Size", default=0.5)

plant = ls_system(
    ls_axiom("FLeaf(size)+(90)FBud"),
    ls_iterations(0),
    ls_angle(25.0),
    ls_step(1.0),
    ls_param("size", size),
    ls_marker("Leaf", "size"),
    ls_marker("Bud"),
)

leaf_points = ls_points(plant, marker="Leaf")
bud_points = ls_points(plant, marker="Bud")
leaves = instance_on_points(cube(0.2), leaf_points)
buds = instance_on_points(cube(0.1), bud_points)

output("Geometry", join(leaves, buds))
