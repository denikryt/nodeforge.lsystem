from packages import lsystem as ls

# Marker extraction and marker parameters.

size = input_float("Size", default=0.5)

plant = ls.system(
    ls.axiom("FLeaf(size)+(90)FBud"),
    ls.iterations(0),
    ls.angle(25.0),
    ls.step(1.0),
    ls.param("size", size),
    ls.marker("Leaf", "size"),
    ls.marker("Bud"),
)

leaf_points = ls.points(plant, marker="Leaf")
bud_points = ls.points(plant, marker="Bud")
leaves = instance_on_points(cube(0.2), leaf_points)
buds = instance_on_points(cube(0.1), bud_points)

output("Geometry", join(leaves, buds))
