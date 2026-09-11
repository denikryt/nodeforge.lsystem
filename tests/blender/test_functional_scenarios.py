"""End-to-end Blender evaluation for the public NodeForge L-System API."""

from __future__ import annotations

import bpy

from NodeForge import compiler, generated_resources
import helpers


def _manifest_refs(group):
    manifest = generated_resources.read_group_manifest(group)
    assert manifest is not None
    return manifest, generated_resources.manifest_resources(manifest)


def _resource_kinds(group):
    _manifest, refs = _manifest_refs(group)
    return refs, sorted(ref.kind for ref in refs)


def _eval_geometry(group, name, inputs=None, *, curve_to_mesh=True):
    wrapper = bpy.data.node_groups.new(name + "_Wrapper", "GeometryNodeTree")
    for item in group.interface.items_tree:
        if getattr(item, "item_type", None) == "SOCKET" and getattr(item, "in_out", None) == "INPUT":
            wrapper.interface.new_socket(name=item.name, in_out="INPUT", socket_type=item.socket_type)
    wrapper.interface.new_socket(name="Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")

    group_input = wrapper.nodes.new("NodeGroupInput")
    group_output = wrapper.nodes.new("NodeGroupOutput")
    group_output.is_active_output = True
    group_node = wrapper.nodes.new("GeometryNodeGroup")
    group_node.node_tree = group
    for item in wrapper.interface.items_tree:
        if getattr(item, "item_type", None) == "SOCKET" and getattr(item, "in_out", None) == "INPUT":
            wrapper.links.new(group_input.outputs[item.name], group_node.inputs[item.name])

    output_socket = group_node.outputs["Geometry"]
    if curve_to_mesh:
        curve_node = wrapper.nodes.new("GeometryNodeCurveToMesh")
        wrapper.links.new(output_socket, curve_node.inputs["Curve"])
        output_socket = curve_node.outputs["Mesh"]
    wrapper.links.new(output_socket, group_output.inputs["Geometry"])

    base_mesh = bpy.data.meshes.new(name + "_Base")
    obj = bpy.data.objects.new(name + "_Object", base_mesh)
    bpy.context.collection.objects.link(obj)
    modifier = obj.modifiers.new("NodeForge", "NODES")
    modifier.node_group = wrapper
    for socket_name, value in (inputs or {}).items():
        helpers._set_modifier_input(modifier, wrapper, socket_name, value)
    obj.update_tag()
    bpy.context.view_layer.update()
    snapshot = helpers._evaluated_mesh_snapshot(obj)
    return wrapper, obj, base_mesh, snapshot


def _cleanup_evaluation(result):
    wrapper, obj, base_mesh, _snapshot = result
    helpers._cleanup_runtime_eval_objects(wrapper, obj, base_mesh)


def test_static_koch_rewrite_and_baked_geometry():
    group = compiler.create_expression_group('''
geo = ls_system(
    ls_axiom("F"),
    ls_rule("F", "F+F--F+F"),
    ls_iterations(2),
    ls_angle(60),
    ls_step(1.0),
)
output("Geometry", geo)
''', "NFTest_LSystem_Static_Koch")
    refs, kinds = _resource_kinds(group)
    assert kinds == ["CURVE", "OBJECT"]
    curve = bpy.data.curves.get(next(ref.name for ref in refs if ref.kind == "CURVE"))
    assert curve is not None
    assert sum(len(spline.points) for spline in curve.splines) == 32
    evaluated = _eval_geometry(group, "NFTest_LSystem_Static_Koch_Eval")
    try:
        vertices, edges, polygons = evaluated[3]
        assert len(vertices) == 32
        assert len(edges) == 16
        assert polygons == 0
        assert vertices[-1] == (9.0, 0.0, 0.0)
    finally:
        _cleanup_evaluation(evaluated)


def test_runtime_branch_free_angle_and_step_update_geometry():
    group = compiler.create_expression_group('''
angle = input_float("Angle", default=90.0)
step = input_float("Step", default=1.0)
geo = ls_system(ls_axiom("F+F"), ls_iterations(0), ls_angle(angle), ls_step(step))
output("Geometry", geo)
''', "NFTest_LSystem_Runtime_BranchFree")
    _refs, kinds = _resource_kinds(group)
    assert kinds == ["MESH", "OBJECT"]
    first = _eval_geometry(group, "NFTest_LSystem_Runtime_BranchFree_A", {"Angle": 90, "Step": 1})
    second = _eval_geometry(group, "NFTest_LSystem_Runtime_BranchFree_B", {"Angle": 0, "Step": 2})
    try:
        assert first[3][0][-1] == (1.0, 1.0, 0.0)
        assert second[3][0][-1] == (4.0, 0.0, 0.0)
        assert len(first[3][1]) == len(second[3][1]) == 2
    finally:
        _cleanup_evaluation(first)
        _cleanup_evaluation(second)


def test_runtime_branch_stack_restores_position_and_heading():
    group = compiler.create_expression_group('''
angle = input_float("Angle", default=90.0)
step = input_float("Step", default=1.0)
geo = ls_system(ls_axiom("F[+F]F[-F]F"), ls_iterations(0), ls_angle(angle), ls_step(step))
output("Geometry", geo)
''', "NFTest_LSystem_Runtime_Branched")
    _refs, kinds = _resource_kinds(group)
    assert kinds == ["MESH", "OBJECT"]
    evaluated = _eval_geometry(group, "NFTest_LSystem_Runtime_Branched_Eval", {"Angle": 90, "Step": 1})
    try:
        vertices, edges, polygons = evaluated[3]
        assert len(edges) == 5
        assert polygons == 0
        coordinates = set(vertices)
        assert (1.0, 1.0, 0.0) in coordinates
        assert (2.0, -1.0, 0.0) in coordinates
        assert (3.0, 0.0, 0.0) in coordinates
    finally:
        _cleanup_evaluation(evaluated)


def test_parameterized_draw_move_and_turn_modules():
    group = compiler.create_expression_group('''
length = input_float("Length", default=2.0)
turn = input_float("Turn", default=90.0)
geo = ls_system(
    ls_axiom("F(length)+(turn)f(length)F(length)-(turn)F(length)"),
    ls_iterations(0),
    ls_angle(30),
    ls_step(1),
    ls_param("length", length),
    ls_param("turn", turn),
)
output("Geometry", geo)
''', "NFTest_LSystem_Parametric_Modules")
    evaluated = _eval_geometry(group, "NFTest_LSystem_Parametric_Eval", {"Length": 2, "Turn": 90})
    try:
        vertices, edges, polygons = evaluated[3]
        assert len(edges) == 3
        assert polygons == 0
        assert vertices[-1] == (4.0, 4.0, 0.0)
    finally:
        _cleanup_evaluation(evaluated)


def test_markers_parameters_ls_points_and_instances():
    group = compiler.create_expression_group('''
size = input_float("Size", default=0.5)
plant = ls_system(
    ls_axiom("FLeaf(size)+(90)FBud"),
    ls_iterations(0),
    ls_angle(25),
    ls_step(1),
    ls_param("size", size),
    ls_marker("Leaf", "size"),
    ls_marker("Bud"),
)
leaf_points = ls_points(plant, marker="Leaf")
bud_points = ls_points(plant, marker="Bud")
leaves = instance_on_points(cube(0.2), leaf_points)
buds = instance_on_points(cube(0.1), bud_points)
output("Geometry", join(leaves, buds))
''', "NFTest_LSystem_Markers")
    refs, kinds = _resource_kinds(group)
    assert kinds == ["CURVE", "MESH", "OBJECT", "OBJECT"]
    marker_mesh = next(bpy.data.meshes.get(ref.name) for ref in refs if ref.kind == "MESH")
    assert marker_mesh is not None
    assert len(marker_mesh.vertices) == 2
    for name in (
        "nf_lsys_marker_id_a", "nf_lsys_marker_id_b", "nf_lsys_marker_id_c", "nf_lsys_marker_id_d",
        "nf_lsys_marker_tangent", "size",
    ):
        assert marker_mesh.attributes.get(name) is not None
    evaluated = _eval_geometry(group, "NFTest_LSystem_Markers_Eval", {"Size": 0.5}, curve_to_mesh=False)
    try:
        vertices, _edges, polygons = evaluated[3]
        assert len(vertices) == 16
        assert polygons == 12
    finally:
        _cleanup_evaluation(evaluated)
