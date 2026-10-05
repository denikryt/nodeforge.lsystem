from packages import lsystem

# Marker extraction and marker parameters.

size = input_float("Size", default=0.5)

plant = generate_lsystem(
    axiom("FLeaf(size)+(90)FBud"),
    iterations(0),
    angle(25.0),
    step(1.0),
    param("size", size),
    marker("Leaf", "size"),
    marker("Bud"),
)

leaf_points = lsystem.points(plant, marker="Leaf")
bud_points = lsystem.points(plant, marker="Bud")
leaves = instance_on_points(cube(0.2), leaf_points)
buds = instance_on_points(cube(0.1), bud_points)

output("Geometry", join(leaves, buds))
