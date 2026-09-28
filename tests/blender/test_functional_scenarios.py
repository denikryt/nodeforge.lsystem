"""End-to-end Blender evaluation for the public NodeForge L-System API."""

from __future__ import annotations

import bpy
import pytest

from NodeForge import compiler, generated_resources
from NodeForge.extension_api import ExtensionBackendContext, ExtensionBackendValue
from NodeForge.extension_registry import ExtensionRegistry
from NodeForge.nf_types import NFType
from NodeForge.errors import CompileError
import helpers


def _manifest_refs(group):
    manifest = generated_resources.read_group_manifest(group)
    assert manifest is not None
    return manifest, generated_resources.manifest_resources(manifest)


def _resource_kinds(group):
    _manifest, refs = _manifest_refs(group)
    return refs, sorted(ref.kind for ref in refs)


def _eval_geometry(group, name, inputs=None, *, curve_to_mesh=True, output_name="Geometry"):
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

    output_socket = group_node.outputs[output_name]
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
        identifier = next(
            item.identifier for item in wrapper.interface.items_tree
            if getattr(item, "item_type", None) == "SOCKET"
            and getattr(item, "in_out", None) == "INPUT"
            and item.name == socket_name
        )
        modifier[identifier] = value
    obj.update_tag()
    bpy.context.view_layer.update()
    snapshot = helpers._evaluated_mesh_snapshot(obj)
    return wrapper, obj, base_mesh, snapshot


def _cleanup_evaluation(result):
    wrapper, obj, base_mesh, _snapshot = result
    helpers._cleanup_runtime_eval_objects(wrapper, obj, base_mesh)



def test_semantic_part_list_literal_star_compiles_through_generic_extension_path():
    """A source list of persisted L-System semantic records compiles through generic semantic LIST expansion."""
    group = compiler.create_expression_group('''
angle_value = input_float("Angle", default=25.0)
axiom = ls_axiom("F")
angle = ls_angle(angle_value)
parts = [axiom, ls_iterations(2), angle, ls_step(1)]
geo = ls_system(*parts)
output("Geometry", geo)
''', "NFTest_LSystem_SemanticListStar")
    assert group is not None
    assert any(
        item.name == "Angle"
        for item in group.interface.items_tree
        if getattr(item, "item_type", None) == "SOCKET"
    )

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
        "nf_lsys_marker_tangent", "nf_lsys_marker_up", "size",
    ):
        assert marker_mesh.attributes.get(name) is not None
    evaluated = _eval_geometry(group, "NFTest_LSystem_Markers_Eval", {"Size": 0.5}, curve_to_mesh=False)
    try:
        vertices, _edges, polygons = evaluated[3]
        assert len(vertices) == 16
        assert polygons == 12
    finally:
        _cleanup_evaluation(evaluated)


def test_static_spatial_turtle_pitch_roll_and_branch_restore():
    group = compiler.create_expression_group('''
geo = ls_system(
    ls_axiom("F[&(90)F]F"),
    ls_iterations(0),
    ls_angle(90),
    ls_step(1),
)
output("Geometry", geo)
''', "NFTest_LSystem_Static_Spatial")
    evaluated = _eval_geometry(group, "NFTest_LSystem_Static_Spatial_Eval")
    try:
        vertices, edges, polygons = evaluated[3]
        assert len(edges) == 3
        assert polygons == 0
        coordinates = set(vertices)
        assert (1.0, 0.0, -1.0) in coordinates
        assert (2.0, 0.0, 0.0) in coordinates
    finally:
        _cleanup_evaluation(evaluated)


def test_runtime_spatial_pitch_roll_updates_without_topology_change():
    group = compiler.create_expression_group('''
pitch = input_float("Pitch", default=45.0)
roll = input_float("Roll", default=90.0)
step = input_float("Step", default=1.0)
geo = ls_system(
    ls_axiom("F/(roll)[&(pitch)F]F"),
    ls_iterations(0),
    ls_angle(25),
    ls_step(step),
    ls_param("pitch", pitch),
    ls_param("roll", roll),
)
output("Geometry", geo)
''', "NFTest_LSystem_Runtime_Spatial")
    _refs, kinds = _resource_kinds(group)
    assert kinds == ["MESH", "OBJECT"]
    assert any(node.bl_idname == "GeometryNodeRepeatInput" for node in group.nodes)
    first = _eval_geometry(group, "NFTest_LSystem_Runtime_Spatial_A", {"Pitch": 45, "Roll": 90, "Step": 1})
    second = _eval_geometry(group, "NFTest_LSystem_Runtime_Spatial_B", {"Pitch": 0, "Roll": 0, "Step": 2})
    try:
        assert len(first[3][1]) == len(second[3][1]) == 3
        assert set(first[3][0]) != set(second[3][0])
        assert any(abs(v[2]) > 1e-5 or abs(v[1]) > 1e-5 for v in first[3][0])
    finally:
        _cleanup_evaluation(first)
        _cleanup_evaluation(second)


def test_static_marker_has_up_orientation_attribute():
    group = compiler.create_expression_group('''
plant = ls_system(
    ls_axiom("/Leaf"),
    ls_iterations(0),
    ls_angle(90),
    ls_step(1),
    ls_marker("Leaf"),
)
output("Geometry", plant)
''', "NFTest_LSystem_Static_Marker_Up")
    refs, kinds = _resource_kinds(group)
    assert kinds == ["MESH", "OBJECT"]
    marker_mesh = next(bpy.data.meshes.get(ref.name) for ref in refs if ref.kind == "MESH")
    assert marker_mesh.attributes.get("nf_lsys_marker_tangent") is not None
    assert marker_mesh.attributes.get("nf_lsys_marker_up") is not None
    tangent = marker_mesh.attributes["nf_lsys_marker_tangent"].data[0].vector
    up = marker_mesh.attributes["nf_lsys_marker_up"].data[0].vector
    assert abs(tangent.length - 1.0) < 1e-5
    assert abs(up.length - 1.0) < 1e-5
    assert abs(tangent.dot(up)) < 1e-5
    assert abs(up.y + 1.0) < 1e-5


def test_spatial_runtime_generated_resource_failure_is_atomic(monkeypatch):
    before_names = {mesh.name for mesh in bpy.data.meshes}
    original_new_mesh = ExtensionBackendContext.new_generated_mesh

    def fail_after_mesh(self, *, role, name_hint=""):
        original_new_mesh(self, role=role, name_hint=name_hint)
        raise RuntimeError("injected failure after transaction-owned mesh creation")

    monkeypatch.setattr(ExtensionBackendContext, "new_generated_mesh", fail_after_mesh)
    with pytest.raises(RuntimeError):
        compiler.create_expression_group('''
pitch = input_float("Pitch", default=35.0)
geo = ls_system(
    ls_axiom("F&(pitch)F"),
    ls_iterations(0),
    ls_angle(25),
    ls_step(1),
    ls_param("pitch", pitch),
)
output("Geometry", geo)
''', "NFTest_LSystem_Spatial_Resource_Fail")
    leaked = sorted(name for name in {mesh.name for mesh in bpy.data.meshes} - before_names if name.startswith("NodeForge."))
    assert leaked == []


def test_runtime_marker_orientation_tracks_spatial_roll():
    group = compiler.create_expression_group('''
roll = input_float("Roll", default=90.0)
plant = ls_system(
    ls_axiom("/(roll)Leaf"),
    ls_iterations(0),
    ls_angle(25),
    ls_step(1),
    ls_param("roll", roll),
    ls_marker("Leaf"),
)
output("Geometry", ls_points(plant, marker="Leaf"))
''', "NFTest_LSystem_Runtime_Marker_Orientation")
    result = _eval_geometry(group, "NFTest_LSystem_Runtime_Marker_Orientation_Eval", {"Roll": 90}, curve_to_mesh=False)
    wrapper, obj, base_mesh, _snapshot = result
    try:
        depsgraph = bpy.context.evaluated_depsgraph_get()
        depsgraph.update()
        evaluated_obj = obj.evaluated_get(depsgraph)
        mesh = evaluated_obj.to_mesh()
        try:
            tangent_attr = mesh.attributes.get("nf_lsys_marker_tangent")
            up_attr = mesh.attributes.get("nf_lsys_marker_up")
            assert tangent_attr is not None
            assert up_attr is not None
            tangent = tangent_attr.data[0].vector
            up = up_attr.data[0].vector
            assert abs(tangent.length - 1.0) < 1e-5
            assert abs(up.length - 1.0) < 1e-5
            assert abs(tangent.dot(up)) < 1e-5
            assert abs(tangent.x - 1.0) < 1e-5
            assert abs(up.y + 1.0) < 1e-5
        finally:
            evaluated_obj.to_mesh_clear()
    finally:
        helpers._cleanup_runtime_eval_objects(wrapper, obj, base_mesh)


def test_spatial_rotation_parser_and_validation_contract():
    # Literal and declared runtime arguments are accepted for every new spatial rotation.
    group = compiler.create_expression_group(r"""
pitch = input_float("Pitch", default=30.0)
roll = input_float("Roll", default=40.0)
geo = ls_system(
    ls_axiom("^(30)&(pitch)/(roll)\\(roll)F"),
    ls_iterations(0),
    ls_angle(25),
    ls_step(1),
    ls_param("pitch", pitch),
    ls_param("roll", roll),
)
output("Geometry", geo)
""", "NFTest_LSystem_Spatial_Syntax")
    assert group is not None

    invalid_sources = (
        'ls_axiom("^()F")',
        'ls_axiom("&(1,2)F")',
        'ls_axiom("/(missing)F")',
        'ls_axiom("F?F")',
    )
    for index, axiom_expr in enumerate(invalid_sources):
        with pytest.raises(CompileError):
            compiler.create_expression_group(f"""
geo = ls_system(
    {axiom_expr},
    ls_iterations(0),
    ls_angle(25),
    ls_step(1),
)
output("Geometry", geo)
""", f"NFTest_LSystem_Spatial_Invalid_{index}")


def test_static_spatial_planar_compatibility_roll_and_noncommutativity():
    planar = compiler.create_expression_group('''
geo = ls_system(ls_axiom("F+F"), ls_iterations(0), ls_angle(90), ls_step(1))
output("Geometry", geo)
''', "NFTest_LSystem_Static_Planar_Compatibility")
    planar_eval = _eval_geometry(planar, "NFTest_LSystem_Static_Planar_Compatibility_Eval")
    try:
        assert planar_eval[3][0][-1] == (1.0, 1.0, 0.0)
    finally:
        _cleanup_evaluation(planar_eval)

    # Roll alone does not move the turtle, but it changes the plane used by later pitch.
    rolled = compiler.create_expression_group('''
geo = ls_system(ls_axiom("/(90)^(90)F"), ls_iterations(0), ls_angle(25), ls_step(1))
output("Geometry", geo)
''', "NFTest_LSystem_Static_Roll")
    rolled_eval = _eval_geometry(rolled, "NFTest_LSystem_Static_Roll_Eval")
    try:
        endpoint = rolled_eval[3][0][-1]
        assert abs(endpoint[1]) > 0.99
        assert abs(endpoint[0]) < 1e-5
        assert abs(endpoint[2]) < 1e-5
    finally:
        _cleanup_evaluation(rolled_eval)

    first = compiler.create_expression_group('''
geo = ls_system(ls_axiom("+(90)^(90)F"), ls_iterations(0), ls_angle(25), ls_step(1))
output("Geometry", geo)
''', "NFTest_LSystem_Static_Rotation_Order_A")
    second = compiler.create_expression_group('''
geo = ls_system(ls_axiom("^(90)+(90)F"), ls_iterations(0), ls_angle(25), ls_step(1))
output("Geometry", geo)
''', "NFTest_LSystem_Static_Rotation_Order_B")
    first_eval = _eval_geometry(first, "NFTest_LSystem_Static_Rotation_Order_A_Eval")
    second_eval = _eval_geometry(second, "NFTest_LSystem_Static_Rotation_Order_B_Eval")
    try:
        assert first_eval[3][0][-1] != second_eval[3][0][-1]
    finally:
        _cleanup_evaluation(first_eval)
        _cleanup_evaluation(second_eval)


def test_static_marker_orientation_restores_after_branch():
    group = compiler.create_expression_group('''
plant = ls_system(
    ls_axiom("F[/(90)&(90)BranchLeaf]ParentLeaf"),
    ls_iterations(0),
    ls_angle(25),
    ls_step(1),
    ls_marker("BranchLeaf"),
    ls_marker("ParentLeaf"),
)
output("Geometry", plant)
''', "NFTest_LSystem_Static_Marker_Branch_Restore")
    refs, _kinds = _resource_kinds(group)
    marker_mesh = next(bpy.data.meshes.get(ref.name) for ref in refs if ref.kind == "MESH")
    up_attr = marker_mesh.attributes["nf_lsys_marker_up"]
    tangent_attr = marker_mesh.attributes["nf_lsys_marker_tangent"]
    # Marker point order follows the stream: branch marker first, restored parent marker second.
    branch_up = up_attr.data[0].vector
    parent_up = up_attr.data[1].vector
    branch_tangent = tangent_attr.data[0].vector
    parent_tangent = tangent_attr.data[1].vector
    assert abs(branch_tangent.dot(branch_up)) < 1e-5
    assert abs(parent_tangent.dot(parent_up)) < 1e-5
    assert abs(parent_tangent.x - 1.0) < 1e-5
    assert abs(parent_up.z - 1.0) < 1e-5
    assert tuple(round(v, 5) for v in branch_up) != tuple(round(v, 5) for v in parent_up)


def test_runtime_spiral_branch_roll_and_parent_restore_without_recompile():
    group = compiler.create_expression_group('''
pitch = input_float("Pitch", default=45.0)
roll = input_float("Roll", default=0.0)
step = input_float("Step", default=1.0)
geo = ls_system(
    ls_axiom("F/(roll)[&(pitch)F]F"),
    ls_iterations(0),
    ls_angle(25),
    ls_step(step),
    ls_param("pitch", pitch),
    ls_param("roll", roll),
)
output("Geometry", geo)
''', "NFTest_LSystem_Runtime_Spiral_Branch")
    stored_source = compiler._extract_group_source(group)
    first = _eval_geometry(group, "NFTest_LSystem_Runtime_Spiral_Branch_A", {"Pitch": 45, "Roll": 0, "Step": 1})
    second = _eval_geometry(group, "NFTest_LSystem_Runtime_Spiral_Branch_B", {"Pitch": 45, "Roll": 90, "Step": 1})
    try:
        assert len(first[3][1]) == len(second[3][1]) == 3
        assert set(first[3][0]) != set(second[3][0])
        assert (2.0, 0.0, 0.0) in set(first[3][0])
        assert (2.0, 0.0, 0.0) in set(second[3][0])
        assert compiler._extract_group_source(group) == stored_source
    finally:
        _cleanup_evaluation(first)
        _cleanup_evaluation(second)


def test_spatial_runtime_resource_ownership_and_recompile_cleanup():
    source_a = '''
pitch = input_float("Pitch", default=35.0)
geo = ls_system(ls_axiom("F&(pitch)F"), ls_iterations(0), ls_angle(25), ls_step(1), ls_param("pitch", pitch))
output("Geometry", geo)
'''
    source_b = '''
roll = input_float("Roll", default=50.0)
geo = ls_system(ls_axiom("F/(roll)F"), ls_iterations(0), ls_angle(25), ls_step(1), ls_param("roll", roll))
output("Geometry", geo)
'''
    group = compiler.create_expression_group(source_a, "NFTest_LSystem_Spatial_Resource_Ownership")
    manifest_a, refs_a = _manifest_refs(group)
    assert {ref.kind for ref in refs_a} == {"MESH", "OBJECT"}
    assert any(ref.role == "spatial_runtime_command_mesh" for ref in refs_a)
    assert any(ref.role == "spatial_runtime_command_object" for ref in refs_a)
    old_names = {(ref.kind, ref.name) for ref in refs_a}
    compiler.update_expression_group(group, source_b)
    manifest_b, refs_b = _manifest_refs(group)
    assert manifest_b["owner_group_uuid"] == manifest_a["owner_group_uuid"]
    for kind, name in old_names:
        collection = bpy.data.meshes if kind == "MESH" else bpy.data.objects
        assert collection.get(name) is None
    assert {(ref.kind, ref.name) for ref in refs_b}.isdisjoint(old_names)


def _expose_runtime_string_output(group, name="Debug String"):
    """Expose the derivation Repeat output for internal runtime-string assertions."""
    socket = group.interface.new_socket(name=name, in_out="OUTPUT", socket_type="NodeSocketGeometry")
    group_output = next(node for node in group.nodes if node.bl_idname == "NodeGroupOutput")
    derivation = next(
        node for node in group.nodes
        if node.bl_idname == "GeometryNodeRepeatOutput" and len(node.repeat_items) == 1
    )
    group.links.new(derivation.outputs["Geometry"], group_output.inputs[name])
    return socket


def _attribute_scalars(mesh, name):
    attr = mesh.attributes.get(name)
    assert attr is not None, name
    return [item.value for item in attr.data]


def test_runtime_iterations_constructor_contract_and_backend_selection():
    static = compiler.create_expression_group('''
geo = ls_system(ls_axiom("F"), ls_iterations(1), ls_angle(25), ls_step(1))
output("Geometry", geo)
''', "NFTest_LSystem_Static_Iterations_Still_Static")
    assert not any(node.bl_idname == "GeometryNodeDuplicateElements" for node in static.nodes)

    dynamic = compiler.create_expression_group('''
iters = input_int("Iterations", default=2)
geo = ls_system(ls_axiom("A"), ls_rule("A", "FA"), ls_iterations(iters), ls_angle(25), ls_step(1))
output("Geometry", geo)
''', "NFTest_LSystem_Runtime_Iterations_Contract")
    assert len([node for node in dynamic.nodes if node.bl_idname == "GeometryNodeRepeatInput"]) == 2
    assert len([node for node in dynamic.nodes if node.bl_idname == "GeometryNodeDuplicateElements"]) == 1
    assert not any(node.bl_idname == "GeometryNodeSortElements" for node in dynamic.nodes)
    # The only For Each zone belongs to final segment materialization, not rewriting.
    assert len([node for node in dynamic.nodes if node.bl_idname == "GeometryNodeForeachGeometryElementInput"]) == 1

    invalid = (
        'ls_iterations(-1)',
        'ls_iterations(input_float("Bad", default=1.0))',
        'ls_iterations(input_bool("Bad", default=True))',
        'ls_iterations(True)',
        'ls_iterations(cube(1.0))',
    )
    for index, iteration_expr in enumerate(invalid):
        with pytest.raises(CompileError):
            compiler.create_expression_group(f'''
geo = ls_system(ls_axiom("F"), {iteration_expr}, ls_angle(25), ls_step(1))
output("Geometry", geo)
''', f"NFTest_LSystem_Runtime_Iterations_Invalid_{index}")


def test_duplicate_elements_ordering_contract_blender_512():
    group = bpy.data.node_groups.new("NFTest_LSystem_Duplicate_Order", "GeometryNodeTree")
    group.interface.new_socket(name="Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    out = group.nodes.new("NodeGroupOutput")
    out.is_active_output = True
    line = group.nodes.new("GeometryNodeMeshLine")
    line.mode = "OFFSET"
    line.inputs["Count"].default_value = 3
    index = group.nodes.new("GeometryNodeInputIndex")

    store_source = group.nodes.new("GeometryNodeStoreNamedAttribute")
    store_source.data_type = "INT"
    store_source.domain = "POINT"
    store_source.inputs["Name"].default_value = "src"
    group.links.new(line.outputs["Mesh"], store_source.inputs["Geometry"])
    group.links.new(index.outputs["Index"], store_source.inputs["Value"])

    cmp0 = group.nodes.new("FunctionNodeCompare"); cmp0.data_type = "INT"; cmp0.operation = "EQUAL"
    cmp1 = group.nodes.new("FunctionNodeCompare"); cmp1.data_type = "INT"; cmp1.operation = "EQUAL"
    group.links.new(index.outputs["Index"], cmp0.inputs[2]); cmp0.inputs[3].default_value = 0
    group.links.new(index.outputs["Index"], cmp1.inputs[2]); cmp1.inputs[3].default_value = 1
    sw1 = group.nodes.new("GeometryNodeSwitch"); sw1.input_type = "INT"
    sw2 = group.nodes.new("GeometryNodeSwitch"); sw2.input_type = "INT"
    group.links.new(cmp1.outputs[0], sw1.inputs[0]); sw1.inputs[1].default_value = 3; sw1.inputs[2].default_value = 0
    group.links.new(cmp0.outputs[0], sw2.inputs[0]); group.links.new(sw1.outputs[0], sw2.inputs[1]); sw2.inputs[2].default_value = 2

    dup = group.nodes.new("GeometryNodeDuplicateElements")
    dup.domain = "POINT"
    group.links.new(store_source.outputs["Geometry"], dup.inputs["Geometry"])
    group.links.new(sw2.outputs[0], dup.inputs["Amount"])
    store_dup = group.nodes.new("GeometryNodeStoreNamedAttribute")
    store_dup.data_type = "INT"; store_dup.domain = "POINT"; store_dup.inputs["Name"].default_value = "dup"
    group.links.new(dup.outputs["Geometry"], store_dup.inputs["Geometry"])
    group.links.new(dup.outputs["Duplicate Index"], store_dup.inputs["Value"])
    group.links.new(store_dup.outputs["Geometry"], out.inputs["Geometry"])

    evaluated = _eval_geometry(group, "NFTest_LSystem_Duplicate_Order_Eval", curve_to_mesh=False)
    wrapper, obj, base_mesh, _snapshot = evaluated
    try:
        depsgraph = bpy.context.evaluated_depsgraph_get(); depsgraph.update()
        evaluated_obj = obj.evaluated_get(depsgraph); mesh = evaluated_obj.to_mesh()
        try:
            assert _attribute_scalars(mesh, "src") == [0, 0, 2, 2, 2]
            assert _attribute_scalars(mesh, "dup") == [0, 1, 0, 1, 2]
        finally:
            evaluated_obj.to_mesh_clear()
    finally:
        helpers._cleanup_runtime_eval_objects(wrapper, obj, base_mesh)
        if bpy.data.node_groups.get(group.name) is group:
            bpy.data.node_groups.remove(group, do_unlink=True)


def test_runtime_rewriting_changes_topology_without_recompile():
    group = compiler.create_expression_group('''
iters = input_int("Iterations", default=2)
geo = ls_system(ls_axiom("A"), ls_rule("A", "FA"), ls_iterations(iters), ls_angle(25), ls_step(1))
output("Geometry", geo)
''', "NFTest_LSystem_Runtime_Topology")
    source = compiler._extract_group_source(group)
    results = []
    for n in (-3, 0, 1, 2, 5):
        result = _eval_geometry(group, f"NFTest_LSystem_Runtime_Topology_{n}", {"Iterations": n})
        results.append(result)
    try:
        assert [len(item[3][1]) for item in results] == [0, 0, 1, 2, 5]
        assert compiler._extract_group_source(group) == source
    finally:
        for result in results:
            _cleanup_evaluation(result)

    branched = compiler.create_expression_group('''
iters = input_int("Iterations", default=3)
geo = ls_system(ls_axiom("A"), ls_rule("A", "F[+A][-A]"), ls_iterations(iters), ls_angle(45), ls_step(1))
output("Geometry", geo)
''', "NFTest_LSystem_Runtime_Branch_Topology")
    counts = []
    evaluations = []
    for n in (1, 2, 4):
        result = _eval_geometry(branched, f"NFTest_LSystem_Runtime_Branch_Topology_{n}", {"Iterations": n})
        evaluations.append(result); counts.append(len(result[3][1]))
    try:
        assert counts == [1, 3, 15]
    finally:
        for result in evaluations:
            _cleanup_evaluation(result)


def test_runtime_native_rotation_matches_static_spatial_turtle():
    static = compiler.create_expression_group('''
geo = ls_system(
    ls_axiom("A"),
    ls_rule("A", "+(31)^(17)/(23)FA"),
    ls_iterations(4), ls_angle(25), ls_step(0.7)
)
output("Geometry", geo)
''', "NFTest_LSystem_Static_Rotation_Reference")
    dynamic = compiler.create_expression_group('''
iters = input_int("Iterations", default=4)
geo = ls_system(
    ls_axiom("A"),
    ls_rule("A", "+(31)^(17)/(23)FA"),
    ls_iterations(iters), ls_angle(25), ls_step(0.7)
)
output("Geometry", geo)
''', "NFTest_LSystem_Runtime_Native_Rotation")
    a = _eval_geometry(static, "NFTest_LSystem_Static_Rotation_Reference_Eval")
    b = _eval_geometry(dynamic, "NFTest_LSystem_Runtime_Native_Rotation_Eval", {"Iterations": 4})
    try:
        assert a[3][1] == b[3][1]
        assert len(a[3][0]) == len(b[3][0])
        for pa, pb in zip(a[3][0], b[3][0]):
            assert max(abs(x - y) for x, y in zip(pa, pb)) < 1e-5
    finally:
        _cleanup_evaluation(a); _cleanup_evaluation(b)


def test_runtime_predecessor_metadata_isolation_and_parallel_rewrite():
    group = compiler.create_expression_group('''
iters = input_int("Iterations", default=1)
geo = ls_system(
    ls_axiom("A"),
    ls_rule("A", "BC"),
    ls_rule("B", "XYZ"),
    ls_rule("C", "Q"),
    ls_iterations(iters), ls_angle(25), ls_step(1)
)
output("Geometry", geo)
''', "NFTest_LSystem_Runtime_Predecessor_Isolation")
    _expose_runtime_string_output(group)
    # Runtime strings carry only immutable module references. Descriptor insertion
    # order for this grammar is A, B, C, X, Y, Z, Q.
    expected = {1: [1, 2], 2: [3, 4, 5, 6]}
    for n, ids in expected.items():
        result = _eval_geometry(group, f"NFTest_LSystem_Runtime_Predecessor_Isolation_{n}", {"Iterations": n}, curve_to_mesh=False, output_name="Debug String")
        wrapper, obj, base_mesh, _snapshot = result
        try:
            depsgraph = bpy.context.evaluated_depsgraph_get(); depsgraph.update()
            evaluated_obj = obj.evaluated_get(depsgraph); mesh = evaluated_obj.to_mesh()
            try:
                assert _attribute_scalars(mesh, "nf_lsys_module_ref") == ids
                assert mesh.attributes.get("nf_lsys_symbol_id") is None
                assert mesh.attributes.get("nf_lsys_command_kind") is None
            finally:
                evaluated_obj.to_mesh_clear()
        finally:
            helpers._cleanup_runtime_eval_objects(wrapper, obj, base_mesh)

    parallel = compiler.create_expression_group('''
iters = input_int("Iterations", default=1)
geo = ls_system(ls_axiom("AB"), ls_rule("A", "AB"), ls_rule("B", "A"), ls_iterations(iters), ls_angle(25), ls_step(1))
output("Geometry", geo)
''', "NFTest_LSystem_Runtime_Parallel")
    _expose_runtime_string_output(parallel)
    for n, ids in ((0, [0, 1]), (1, [0, 1, 0]), (2, [0, 1, 0, 0, 1])):
        result = _eval_geometry(parallel, f"NFTest_LSystem_Runtime_Parallel_{n}", {"Iterations": n}, curve_to_mesh=False, output_name="Debug String")
        wrapper, obj, base_mesh, _snapshot = result
        try:
            depsgraph = bpy.context.evaluated_depsgraph_get(); depsgraph.update(); eo = obj.evaluated_get(depsgraph); mesh = eo.to_mesh()
            try:
                assert _attribute_scalars(mesh, "nf_lsys_module_ref") == ids
            finally:
                eo.to_mesh_clear()
        finally:
            helpers._cleanup_runtime_eval_objects(wrapper, obj, base_mesh)


def test_runtime_identity_deletion_and_parameter_payload_preservation():
    deletion = compiler.create_expression_group('''
iters = input_int("Iterations", default=1)
geo = ls_system(ls_axiom("AB"), ls_rule("A", ""), ls_iterations(iters), ls_angle(25), ls_step(1), ls_marker("B"))
output("Geometry", ls_points(geo, marker="B"))
''', "NFTest_LSystem_Runtime_Deletion")
    for n in (0, 1):
        result = _eval_geometry(deletion, f"NFTest_LSystem_Runtime_Deletion_{n}", {"Iterations": n}, curve_to_mesh=False)
        try:
            assert len(result[3][0]) == 1
        finally:
            _cleanup_evaluation(result)

    identity = compiler.create_expression_group('''
iters = input_int("Iterations", default=3)
geo = ls_system(ls_axiom("A"), ls_rule("A", "F(0.25)A"), ls_iterations(iters), ls_angle(25), ls_step(9))
output("Geometry", geo)
''', "NFTest_LSystem_Runtime_Identity_Payload")
    result = _eval_geometry(identity, "NFTest_LSystem_Runtime_Identity_Payload_Eval", {"Iterations": 3})
    try:
        vertices, edges, _ = result[3]
        assert len(edges) == 3
        assert max(v[0] for v in vertices) == 0.75
    finally:
        _cleanup_evaluation(result)


def test_runtime_bracket_invariant_and_dynamic_spatial_stack():
    accepted = compiler.create_expression_group('''
iters = input_int("Iterations", default=3)
geo = ls_system(ls_axiom("A"), ls_rule("A", "F[&(45)/(30)A]A"), ls_iterations(iters), ls_angle(25), ls_step(1))
output("Geometry", geo)
''', "NFTest_LSystem_Runtime_Spatial_Stack")
    stack_results = [
        _eval_geometry(accepted, "NFTest_LSystem_Runtime_Spatial_Stack_Eval_2", {"Iterations": 2}),
        _eval_geometry(accepted, "NFTest_LSystem_Runtime_Spatial_Stack_Eval_4", {"Iterations": 4}),
    ]
    try:
        assert [len(result[3][1]) for result in stack_results] == [3, 15]
        assert any(abs(vertex[2]) > 1e-5 for vertex in stack_results[1][3][0])
    finally:
        for result in stack_results:
            _cleanup_evaluation(result)

    bad_sources = (
        'ls_axiom("[]"), ls_rule("[", "")',
        'ls_axiom("A"), ls_rule("A", "[F")',
        'ls_axiom("A"), ls_rule("A", "F]")',
        'ls_axiom("]A"), ls_rule("A", "A")',
    )
    for index, parts in enumerate(bad_sources):
        with pytest.raises(CompileError):
            compiler.create_expression_group(f'''
iters = input_int("Iterations", default=1)
geo = ls_system({parts}, ls_iterations(iters), ls_angle(25), ls_step(1))
output("Geometry", geo)
''', f"NFTest_LSystem_Runtime_Bracket_Invalid_{index}")

    # Explicit stack-shape smoke cases exercise nested and sibling pop/reuse behavior.
    for index, axiom in enumerate(("[]", "[[]]", "[][]", "[[][[]]]")):
        group = compiler.create_expression_group(f'''
iters = input_int("Iterations", default=0)
geo = ls_system(ls_axiom("{axiom}F"), ls_iterations(iters), ls_angle(25), ls_step(1))
output("Geometry", geo)
''', f"NFTest_LSystem_Runtime_StackShape_{index}")
        result = _eval_geometry(group, f"NFTest_LSystem_Runtime_StackShape_Eval_{index}", {"Iterations": 0})
        try:
            assert len(result[3][1]) == 1
        finally:
            _cleanup_evaluation(result)

    names = [
        node.inputs[0].default_value
        for node in accepted.nodes
        if node.bl_idname == "GeometryNodeInputNamedAttribute" and node.inputs and node.inputs[0].bl_idname == "NodeSocketString"
    ]
    assert "nf_lsys_stack_branch_depth" in names
    assert any(node.bl_idname == "FunctionNodeCompare" and node.data_type == "INT" and node.operation == "EQUAL" for node in accepted.nodes)


def test_runtime_markers_preserve_schema_iteration_orientation_and_params():
    group = compiler.create_expression_group('''
iters = input_int("Iterations", default=2)
roll = input_float("Roll", default=90.0)
size = input_float("Size", default=0.5)
geo = ls_system(
    ls_axiom("A"),
    ls_rule("A", "/(roll)FLeaf(size)A"),
    ls_iterations(iters), ls_angle(25), ls_step(1),
    ls_param("roll", roll), ls_param("size", size),
    ls_marker("Leaf", "size")
)
output("Geometry", ls_points(geo, marker="Leaf"))
''', "NFTest_LSystem_Runtime_Marker_Schema")
    results = [
        _eval_geometry(group, "NFTest_LSystem_Runtime_Marker_Schema_Eval_0", {"Iterations": 2, "Roll": 0, "Size": 0.75}, curve_to_mesh=False),
        _eval_geometry(group, "NFTest_LSystem_Runtime_Marker_Schema_Eval_90", {"Iterations": 2, "Roll": 90, "Size": 0.75}, curve_to_mesh=False),
    ]
    orientations = []
    try:
        for result in results:
            wrapper, obj, base_mesh, _snapshot = result
            depsgraph = bpy.context.evaluated_depsgraph_get(); depsgraph.update(); eo = obj.evaluated_get(depsgraph); mesh = eo.to_mesh()
            try:
                assert len(mesh.vertices) == 2
                for name in (
                    "nf_lsys_marker_tangent", "nf_lsys_marker_up", "nf_lsys_marker_depth",
                    "nf_lsys_marker_path_id", "nf_lsys_marker_iteration", "size",
                ):
                    assert mesh.attributes.get(name) is not None
                assert _attribute_scalars(mesh, "nf_lsys_marker_iteration") == [0, 0]
                assert _attribute_scalars(mesh, "size") == pytest.approx([0.75, 0.75])
                orientations.append([tuple(round(float(v), 5) for v in item.vector) for item in mesh.attributes["nf_lsys_marker_up"].data])
            finally:
                eo.to_mesh_clear()
        assert orientations[0] != orientations[1]
    finally:
        for result in results:
            helpers._cleanup_runtime_eval_objects(result[0], result[1], result[2])


def test_runtime_grammar_resource_ownership_recompile_and_rollback(monkeypatch):
    source_a = '''
iters = input_int("Iterations", default=2)
geo = ls_system(ls_axiom("A"), ls_rule("A", "FA"), ls_iterations(iters), ls_angle(25), ls_step(1))
output("Geometry", geo)
'''
    source_b = '''
iters = input_int("Iterations", default=2)
geo = ls_system(ls_axiom("B"), ls_rule("B", "F[+B][-B]"), ls_iterations(iters), ls_angle(25), ls_step(1))
output("Geometry", geo)
'''
    group = compiler.create_expression_group(source_a, "NFTest_LSystem_Runtime_Resource_Ownership")
    manifest_a, refs_a = _manifest_refs(group)
    roles = {ref.role for ref in refs_a}
    assert roles == {
        "runtime_axiom_mesh", "runtime_axiom_object",
        "runtime_successor_mesh", "runtime_successor_object",
        "runtime_rule_index_mesh", "runtime_rule_index_object",
        "runtime_module_definitions_mesh", "runtime_module_definitions_object",
    }
    old_names = {(ref.kind, ref.name) for ref in refs_a}
    compiler.update_expression_group(group, source_b)
    manifest_b, refs_b = _manifest_refs(group)
    assert manifest_b["owner_group_uuid"] == manifest_a["owner_group_uuid"]
    for kind, name in old_names:
        collection = bpy.data.meshes if kind == "MESH" else bpy.data.objects
        assert collection.get(name) is None
    assert {(ref.kind, ref.name) for ref in refs_b}.isdisjoint(old_names)

    original_new_object = ExtensionBackendContext.new_generated_object

    def fail_before_object(self, data=None, *, role, name_hint=""):
        raise RuntimeError("injected failure after generated Mesh creation")

    def fail_after_object(self, data=None, *, role, name_hint=""):
        original_new_object(self, data, role=role, name_hint=name_hint)
        raise RuntimeError("injected failure after generated Object creation")

    for label, replacement in (("after_mesh", fail_before_object), ("after_object", fail_after_object)):
        before_mesh = set(bpy.data.meshes.keys())
        before_obj = set(bpy.data.objects.keys())
        with monkeypatch.context() as patch:
            patch.setattr(ExtensionBackendContext, "new_generated_object", replacement)
            with pytest.raises(RuntimeError):
                compiler.create_expression_group(source_a, "NFTest_LSystem_Runtime_Resource_Fail_" + label)
        assert [name for name in set(bpy.data.meshes.keys()) - before_mesh if name.startswith("NodeForge.")] == []
        assert [name for name in set(bpy.data.objects.keys()) - before_obj if name.startswith("NodeForge.")] == []


def test_runtime_rule_index_object_failure_rolls_back_all_grammar_resources(monkeypatch):
    source = """
iters = input_int("Iterations", default=2)
geo = ls_system(ls_axiom("A"), ls_rule("A", "FA"), ls_iterations(iters), ls_angle(25), ls_step(1))
output("Geometry", geo)
"""
    original_new_object = ExtensionBackendContext.new_generated_object

    def fail_after_rule_index_object(self, data=None, *, role, name_hint=""):
        obj = original_new_object(self, data, role=role, name_hint=name_hint)
        if role == "runtime_rule_index_object":
            raise RuntimeError("injected rule-index failure")
        return obj

    before_mesh = set(bpy.data.meshes.keys())
    before_obj = set(bpy.data.objects.keys())
    monkeypatch.setattr(ExtensionBackendContext, "new_generated_object", fail_after_rule_index_object)
    with pytest.raises(RuntimeError):
        compiler.create_expression_group(source, "NFTest_LSystem_Runtime_RuleIndex_Fail")
    assert [name for name in set(bpy.data.meshes.keys()) - before_mesh if name.startswith("NodeForge.")] == []
    assert [name for name in set(bpy.data.objects.keys()) - before_obj if name.startswith("NodeForge.")] == []


def test_lsystem_generated_resources_roll_back_on_declared_result_validation_failure(monkeypatch):
    source = """
geo = ls_system(ls_axiom("F"), ls_iterations(0), ls_angle(25), ls_step(1))
output("Geometry", geo)
"""
    original_invoke = ExtensionRegistry.invoke_implementation

    def wrong_result(self, callable_id, *args, **kwargs):
        result = original_invoke(self, callable_id, *args, **kwargs)
        if callable_id.name == "ls_system":
            return ExtensionBackendValue(result.socket, NFType.FLOAT)
        return result

    before_curve = set(bpy.data.curves.keys())
    before_obj = set(bpy.data.objects.keys())
    monkeypatch.setattr(ExtensionRegistry, "invoke_implementation", wrong_result)
    with pytest.raises(CompileError, match="returned FLOAT, expected GEOMETRY"):
        compiler.create_expression_group(source, "NFTest_LSystem_Result_Validation_Fail")
    assert [name for name in set(bpy.data.curves.keys()) - before_curve if name.startswith("NodeForge.")] == []
    assert [name for name in set(bpy.data.objects.keys()) - before_obj if name.startswith("NodeForge.")] == []


def test_supported_lsystem_v2_never_calls_legacy_compiler_compile(monkeypatch):
    source = """
angle = input_float("Angle", default=25.0)
part = ls_angle(angle)
geo = ls_system(ls_axiom("F"), ls_iterations(0), part, ls_step(1))
output("Geometry", geo)
"""

    def forbidden_compile(*_args, **_kwargs):
        raise AssertionError("supported Extension API v2 path reached Compiler.compile()")

    monkeypatch.setattr(compiler.Compiler, "compile", forbidden_compile)
    group = compiler.create_expression_group(source, "NFTest_LSystem_No_Legacy_Compile")
    assert group is not None
