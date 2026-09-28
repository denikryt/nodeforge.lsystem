"""L-System-specific generated Blender resource materialization."""

from __future__ import annotations

import bpy

from NodeForge.extension_api import ExtensionBackendValue


def _link_object_to_context_collection(obj) -> None:
    """Link one generated helper object to the active Blender 5.2 scene collection."""
    bpy.context.scene.collection.objects.link(obj)


def _hide_generated_object(obj) -> None:
    """Keep generated helper objects out of ordinary viewport/render interaction."""
    obj.hide_viewport = True
    obj.hide_render = True
    obj.hide_select = True
    obj.use_fake_user = False


def _write_attribute_values(attribute, values) -> None:
    """Write generated attribute data through the Blender 5.2 bulk-write contract."""
    data = attribute.data
    if len(data) != len(values):
        raise RuntimeError(f"Generated attribute {attribute.name} length mismatch")
    if attribute.data_type == "FLOAT_VECTOR":
        flat = [float(component) for value in values for component in value]
        data.foreach_set("vector", flat)
        return
    if attribute.data_type in {"FLOAT", "INT", "BOOLEAN"}:
        data.foreach_set("value", values)
        return
    raise RuntimeError(
        f"Generated attribute {attribute.name!r} uses unsupported Blender 5.2 data type {attribute.data_type!r}"
    )


def _marker_point_attribute_specs(table):
    """Return the stable marker point-attribute schema for one command table."""
    ids = getattr(table, "marker_id", ()) or [(0, 0, 0, 0)] * len(table.vertices)
    specs = [
        ("nf_lsys_marker_id_a", "INT", [item[0] for item in ids]),
        ("nf_lsys_marker_id_b", "INT", [item[1] for item in ids]),
        ("nf_lsys_marker_id_c", "INT", [item[2] for item in ids]),
        ("nf_lsys_marker_id_d", "INT", [item[3] for item in ids]),
        ("nf_lsys_marker_mask", "BOOLEAN", getattr(table, "marker_mask", [False] * len(table.vertices))),
        ("nf_lsys_marker_tangent", "FLOAT_VECTOR", getattr(table, "marker_tangent", [(0.0, 0.0, 0.0)] * len(table.vertices))),
        ("nf_lsys_marker_up", "FLOAT_VECTOR", getattr(table, "marker_up", [(0.0, 0.0, 1.0)] * len(table.vertices))),
        ("nf_lsys_marker_depth", "INT", getattr(table, "marker_depth", [0] * len(table.vertices))),
        ("nf_lsys_marker_path_id", "INT", getattr(table, "marker_path_id", [0] * len(table.vertices))),
        ("nf_lsys_marker_iteration", "INT", getattr(table, "marker_iteration", [-1] * len(table.vertices))),
    ]
    for name, values in getattr(table, "marker_param_static", {}).items():
        specs.append((name, "FLOAT", values))
        specs.append((f"nf_lsys_marker_param_index_{name}", "INT", getattr(table, "marker_param_index", {})[name]))
    return tuple(specs)


def _create_command_mesh_object_from_specs(
    context,
    table,
    *,
    name_hint: str,
    mesh_role: str,
    object_role: str,
    point_attributes,
    edge_attributes,
):
    """Create one transaction-owned generated command Mesh/Object pair."""
    mesh = context.new_generated_mesh(role=mesh_role, name_hint=name_hint)
    mesh.from_pydata(list(table.vertices), list(table.edges), [])
    mesh.update()
    for attr_name, data_type, values in point_attributes:
        attr = mesh.attributes.new(attr_name, data_type, "POINT")
        _write_attribute_values(attr, values)
    for attr_name, data_type, values in edge_attributes:
        attr = mesh.attributes.new(attr_name, data_type, "EDGE")
        _write_attribute_values(attr, values)
    mesh.update()
    obj = context.new_generated_object(mesh, role=object_role, name_hint=name_hint)
    _link_object_to_context_collection(obj)
    _hide_generated_object(obj)
    return mesh, obj


def create_curve_object_from_segments(context, segments, *, name_hint: str):
    """Create a transaction-owned Curve/Object pair for static turtle segments."""
    curve = context.new_generated_curve(role="static_baked_curve", name_hint=name_hint)
    curve.dimensions = "3D"
    curve.resolution_u = 1
    curve.use_fake_user = False
    for segment in segments:
        spline = curve.splines.new("POLY")
        spline.points.add(1)
        spline.points[0].co = (float(segment.start.x), float(segment.start.y), float(segment.start.z), 1.0)
        spline.points[1].co = (float(segment.end.x), float(segment.end.y), float(segment.end.z), 1.0)
    obj = context.new_generated_object(curve, role="static_baked_object", name_hint=name_hint)
    _link_object_to_context_collection(obj)
    _hide_generated_object(obj)
    return curve, obj


def create_command_mesh_object_from_table(context, table, *, name_hint: str):
    """Create branch-free runtime command data for this package."""
    return _create_command_mesh_object_from_specs(
        context,
        table,
        name_hint=name_hint,
        mesh_role="branch_free_runtime_command_mesh",
        object_role="branch_free_runtime_command_object",
        point_attributes=(
            ("nf_lsys_move_mask", "FLOAT", table.move_mask),
            ("nf_lsys_heading_index", "FLOAT", table.heading_index),
            ("nf_lsys_move_distance_static", "FLOAT", table.move_distance_static),
            ("nf_lsys_move_param_index", "INT", table.move_param_index),
            ("nf_lsys_turn_degrees_static", "FLOAT", table.turn_degrees_static),
            ("nf_lsys_turn_param_index", "INT", table.turn_param_index),
            ("nf_lsys_turn_sign", "FLOAT", table.turn_sign),
        ) + _marker_point_attribute_specs(table),
        edge_attributes=(("nf_lsys_draw_mask", "BOOLEAN", table.draw_mask),),
    )


def create_branch_aware_command_mesh_object_from_table(context, table, *, name_hint: str):
    """Create branch-aware runtime command data for this package."""
    return _create_command_mesh_object_from_specs(
        context,
        table,
        name_hint=name_hint,
        mesh_role="branch_aware_runtime_command_mesh",
        object_role="branch_aware_runtime_command_object",
        point_attributes=(
            ("nf_lsys_move_mask", "FLOAT", table.move_mask),
            ("nf_lsys_heading_index", "FLOAT", table.heading_index),
            ("nf_lsys_path_id", "INT", table.path_id),
            ("nf_lsys_path_depth", "INT", table.path_depth),
            ("nf_lsys_parent_attach_index", "INT", table.parent_attach_index),
            ("nf_lsys_anchor_mask", "BOOLEAN", table.anchor_mask),
            ("nf_lsys_move_distance_static", "FLOAT", table.move_distance_static),
            ("nf_lsys_move_param_index", "INT", table.move_param_index),
            ("nf_lsys_turn_degrees_static", "FLOAT", table.turn_degrees_static),
            ("nf_lsys_turn_param_index", "INT", table.turn_param_index),
            ("nf_lsys_turn_sign", "FLOAT", table.turn_sign),
        ) + _marker_point_attribute_specs(table),
        edge_attributes=(("nf_lsys_draw_mask", "BOOLEAN", table.draw_mask),),
    )


def create_spatial_command_mesh_object_from_table(context, table, *, name_hint: str):
    """Create the sequential command/state mesh used by the spatial runtime backend."""
    n = len(table.vertices)
    initial_position = [(0.0, 0.0, 0.0)] * n
    initial_heading = [(1.0, 0.0, 0.0)] + [(0.0, 0.0, 0.0)] * max(0, n - 1)
    initial_left = [(0.0, 1.0, 0.0)] + [(0.0, 0.0, 0.0)] * max(0, n - 1)
    initial_up = [(0.0, 0.0, 1.0)] + [(0.0, 0.0, 0.0)] * max(0, n - 1)
    return _create_command_mesh_object_from_specs(
        context,
        table,
        name_hint=name_hint,
        mesh_role="spatial_runtime_command_mesh",
        object_role="spatial_runtime_command_object",
        point_attributes=(
            ("nf_lsys_parent_state_index", "INT", table.parent_state_index),
            ("nf_lsys_command_kind", "INT", table.command_kind),
            ("nf_lsys_value_static", "FLOAT", table.value_static),
            ("nf_lsys_value_param_index", "INT", table.value_param_index),
            ("nf_lsys_command_sign", "FLOAT", table.command_sign),
            ("nf_lsys_world_position", "FLOAT_VECTOR", initial_position),
            ("nf_lsys_heading", "FLOAT_VECTOR", initial_heading),
            ("nf_lsys_left", "FLOAT_VECTOR", initial_left),
            ("nf_lsys_up", "FLOAT_VECTOR", initial_up),
        ) + _marker_point_attribute_specs(table),
        edge_attributes=(("nf_lsys_draw_mask", "BOOLEAN", table.draw_mask),),
    )


def create_marker_mesh_object_from_points(context, markers, *, name_hint: str):
    """Create static marker point data and return runtime parameter slots."""
    mesh = context.new_generated_mesh(role="static_marker_mesh", name_hint=name_hint)
    vertices = [(float(m.position.x), float(m.position.y), float(m.position.z)) for m in markers]
    mesh.from_pydata(vertices, [], [])
    mesh.update()
    ids = [m.marker_identity for m in markers]
    attrs = [
        ("nf_lsys_marker_id_a", "INT", [item[0] for item in ids]),
        ("nf_lsys_marker_id_b", "INT", [item[1] for item in ids]),
        ("nf_lsys_marker_id_c", "INT", [item[2] for item in ids]),
        ("nf_lsys_marker_id_d", "INT", [item[3] for item in ids]),
        ("nf_lsys_marker_mask", "BOOLEAN", [True] * len(markers)),
        ("nf_lsys_marker_tangent", "FLOAT_VECTOR", [(float(m.tangent.x), float(m.tangent.y), float(m.tangent.z)) for m in markers]),
        ("nf_lsys_marker_up", "FLOAT_VECTOR", [(float(m.up.x), float(m.up.y), float(m.up.z)) for m in markers]),
        ("nf_lsys_marker_depth", "INT", [int(m.branch_depth) for m in markers]),
        ("nf_lsys_marker_path_id", "INT", [int(m.path_id) for m in markers]),
        ("nf_lsys_marker_iteration", "INT", [int(m.creation_iteration if m.creation_iteration is not None else -1) for m in markers]),
    ]
    runtime_slots: list[tuple[str, ExtensionBackendValue]] = []
    param_names = sorted({name for marker in markers for name in marker.parameters})
    for name in param_names:
        values = []
        indexes = []
        for marker in markers:
            value = marker.parameters.get(name, 0.0)
            if isinstance(value, ExtensionBackendValue):
                slot = -1
                for idx, (slot_name, slot_value) in enumerate(runtime_slots):
                    if slot_name == name and slot_value is value:
                        slot = idx
                        break
                if slot < 0:
                    runtime_slots.append((name, value))
                    slot = len(runtime_slots) - 1
                values.append(0.0)
                indexes.append(slot)
            else:
                values.append(float(value) if type(value) in {int, float} else 0.0)
                indexes.append(-1)
        attrs.append((name, "FLOAT", values))
        attrs.append((f"nf_lsys_marker_param_index_{name}", "INT", indexes))
    for attr_name, data_type, values in attrs:
        attr = mesh.attributes.new(attr_name, data_type, "POINT")
        _write_attribute_values(attr, values)
    mesh.update()
    obj = context.new_generated_object(mesh, role="static_marker_object", name_hint=name_hint)
    _link_object_to_context_collection(obj)
    _hide_generated_object(obj)
    return mesh, obj, tuple(runtime_slots)


def _create_point_table_object(context, table, *, name_hint: str, mesh_role: str, object_role: str, point_attributes):
    """Create a transaction-owned point-only Mesh/Object from explicit table attributes."""
    return _create_command_mesh_object_from_specs(
        context,
        table,
        name_hint=name_hint,
        mesh_role=mesh_role,
        object_role=object_role,
        point_attributes=point_attributes,
        edge_attributes=(),
    )


def create_runtime_axiom_object(context, table, *, name_hint: str):
    """Create the immutable point table that seeds a runtime L-string."""
    return _create_point_table_object(
        context,
        table,
        name_hint=name_hint,
        mesh_role="runtime_axiom_mesh",
        object_role="runtime_axiom_object",
        point_attributes=table.point_attributes(),
    )


def create_runtime_successor_object(context, table, *, name_hint: str):
    """Create the immutable contiguous successor-module point table."""
    return _create_point_table_object(
        context,
        table,
        name_hint=name_hint,
        mesh_role="runtime_successor_mesh",
        object_role="runtime_successor_object",
        point_attributes=table.point_attributes(),
    )


def create_runtime_module_definitions_object(context, table, *, name_hint: str):
    """Create immutable module descriptors addressed by runtime module references."""
    return _create_point_table_object(
        context,
        table,
        name_hint=name_hint,
        mesh_role="runtime_module_definitions_mesh",
        object_role="runtime_module_definitions_object",
        point_attributes=table.point_attributes(),
    )


def create_runtime_rule_index_object(context, table, *, name_hint: str):
    """Create the immutable symbol-id to production metadata point table."""
    return _create_point_table_object(
        context,
        table,
        name_hint=name_hint,
        mesh_role="runtime_rule_index_mesh",
        object_role="runtime_rule_index_object",
        point_attributes=table.point_attributes(),
    )
