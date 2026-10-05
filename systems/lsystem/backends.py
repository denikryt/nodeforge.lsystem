"""Backend selection and materialization for L-systems."""

from NodeForge.errors import CompileError
from NodeForge.extension_api import ExtensionBackendValue, NFType
from .runtime_tables import (
    DRAW_MASK_ATTR,
    LOCAL_POSITION_ATTR,
    MARKER_DEPTH_ATTR,
    MARKER_ID_ATTRS,
    MARKER_ITERATION_ATTR,
    MARKER_MASK_ATTR,
    MARKER_TANGENT_ATTR,
    MARKER_UP_ATTR,
    MARKER_PATH_ID_ATTR,
    MOVE_DISTANCE_STATIC_ATTR,
    MOVE_PARAM_INDEX_ATTR,
    PARENT_ATTACH_INDEX_ATTR,
    PATH_DEPTH_ATTR,
    PATH_ID_ATTR,
    TURN_DEGREES_STATIC_ATTR,
    TURN_PARAM_INDEX_ATTR,
    TURN_SIGN_ATTR,
    WORLD_POSITION_ATTR,
    PARENT_STATE_INDEX_ATTR, COMMAND_KIND_ATTR, COMMAND_VALUE_STATIC_ATTR, COMMAND_VALUE_PARAM_INDEX_ATTR, COMMAND_SIGN_ATTR,
    HEADING_ATTR, LEFT_ATTR, UP_ATTR, CMD_MOVE_DRAW, CMD_MOVE_NO_DRAW, CMD_YAW, CMD_PITCH, CMD_ROLL, CMD_MARKER,
)
from .modules import marker_identity



def _new_node(context, bl_idname: str, x=0, y=0):
    """Create one Blender node in the current extension-owned group."""
    node = context.group.nodes.new(bl_idname)
    node.location = (x, y)
    return node


def _is_number_type(typ: NFType) -> bool:
    """Return whether *typ* is one of NodeForge's public scalar numeric types."""
    return typ in {NFType.FLOAT, NFType.INT}


def _value(context, value, x=0, y=0) -> ExtensionBackendValue:
    """Materialize one already-normalized detached number as a Float node."""
    if type(value) not in {int, float}:
        raise CompileError("L-system Float constant must be a detached numeric value")
    node = _new_node(context, "ShaderNodeValue", x, y)
    node.label = str(value)
    node.outputs[0].default_value = float(value)
    return context.value(node.outputs[0], NFType.FLOAT)


def _int_value(context, value, x=0, y=0) -> ExtensionBackendValue:
    """Materialize one already-normalized detached Int as an Integer node."""
    if type(value) is not int:
        raise CompileError("L-system Int constant must be a detached integer")
    node = _new_node(context, "FunctionNodeInputInt", x, y)
    node.label = str(value)
    node.integer = value
    return context.value(node.outputs[0], NFType.INT)


def _math(context, operation: str, args, x=0, y=0) -> ExtensionBackendValue:
    """Create one physical Float Math node for typed numeric backend values."""
    node = _new_node(context, "ShaderNodeMath", x, y)
    node.operation = operation
    for index, arg in enumerate(args):
        if not isinstance(arg, ExtensionBackendValue) or not _is_number_type(arg.typ):
            raise CompileError(f"L-system Math {operation} expects numeric backend values")
        context.group.links.new(arg.socket, node.inputs[index])
    return context.value(node.outputs[0], NFType.FLOAT)


def _vector_math(context, operation: str, args, out_type=NFType.VECTOR, x=0, y=0) -> ExtensionBackendValue:
    """Create one physical Vector Math node for already-typed backend values."""
    node = _new_node(context, "ShaderNodeVectorMath", x, y)
    node.operation = operation
    vector_index = 0
    for arg in args:
        if not isinstance(arg, ExtensionBackendValue):
            raise CompileError(f"L-system Vector Math {operation} expects backend values")
        if arg.typ is NFType.VECTOR:
            context.group.links.new(arg.socket, node.inputs[vector_index])
            vector_index += 1
        elif _is_number_type(arg.typ):
            context.group.links.new(arg.socket, node.inputs[3])
        else:
            raise CompileError(f"L-system Vector Math {operation} got unsupported type {arg.typ}")
    output_index = 1 if out_type is NFType.FLOAT else 0
    return context.value(node.outputs[output_index], out_type)


def _combine_xyz_mixed(context, components, x=0, y=0) -> ExtensionBackendValue:
    """Build one Vector from backend numeric values and detached constants."""
    if len(components) != 3:
        raise CompileError("L-system vector helper expects exactly three components")
    node = _new_node(context, "ShaderNodeCombineXYZ", x, y)
    for index, value in enumerate(components):
        if isinstance(value, ExtensionBackendValue):
            if not _is_number_type(value.typ):
                raise CompileError("L-system vector helper expects numeric components")
            context.group.links.new(value.socket, node.inputs[index])
        elif type(value) in {int, float}:
            node.inputs[index].default_value = float(value)
        else:
            raise CompileError("L-system vector helper expects numeric components")
    return context.value(node.outputs[0], NFType.VECTOR)


def _separate_xyz(context, value: ExtensionBackendValue, component: str, x=0, y=0) -> ExtensionBackendValue:
    """Extract one scalar component from a backend Vector value."""
    if value.typ is not NFType.VECTOR or component not in {"x", "y", "z"}:
        raise CompileError("L-system vector component helper received incompatible input")
    node = _new_node(context, "ShaderNodeSeparateXYZ", x, y)
    context.group.links.new(value.socket, node.inputs[0])
    return context.value(node.outputs[{"x": 0, "y": 1, "z": 2}[component]], NFType.FLOAT)


def _compare(context, operation: str, left: ExtensionBackendValue, right: ExtensionBackendValue, x=0, y=0) -> ExtensionBackendValue:
    """Create one Blender 5.2 Compare node from already-resolved public NFTypes."""
    if left.typ is NFType.INT and right.typ is NFType.INT:
        data_type = "INT"
    elif _is_number_type(left.typ) and _is_number_type(right.typ):
        data_type = "FLOAT"
    elif left.typ is right.typ and left.typ in {NFType.BOOL, NFType.VECTOR}:
        data_type = {NFType.BOOL: "INT", NFType.VECTOR: "VECTOR"}[left.typ]
    else:
        raise CompileError("L-system comparison inputs have incompatible types")
    node = _new_node(context, "FunctionNodeCompare", x, y)
    node.operation = operation
    node.data_type = data_type
    if data_type == "FLOAT" and operation in {"EQUAL", "NOT_EQUAL"}:
        _input_socket(node, "Epsilon").default_value = 0.0
    context.group.links.new(left.socket, _input_socket(node, "A"))
    context.group.links.new(right.socket, _input_socket(node, "B"))
    return context.value(_output_socket(node, "Result"), NFType.BOOL)



def _boolean_math(context, operation: str, args, x=0, y=0) -> ExtensionBackendValue:
    """Create one Boolean Math node from Bool backend values."""
    node = _new_node(context, "FunctionNodeBooleanMath", x, y)
    node.operation = operation
    for index, arg in enumerate(args):
        if not isinstance(arg, ExtensionBackendValue) or arg.typ is not NFType.BOOL:
            raise CompileError("L-system Boolean Math expects Bool values")
        context.group.links.new(arg.socket, node.inputs[index])
    return context.value(node.outputs[0], NFType.BOOL)


def _switch(context, condition: ExtensionBackendValue, false_value: ExtensionBackendValue, true_value: ExtensionBackendValue, x=0, y=0) -> ExtensionBackendValue:
    """Create one Blender 5.2 Switch for backend values of the same type."""
    if condition.typ is not NFType.BOOL:
        raise CompileError("L-system switch condition must be Bool")
    if false_value.typ is not true_value.typ:
        raise CompileError("L-system switch values must have the same NFType")
    input_type = {
        NFType.FLOAT: "FLOAT",
        NFType.INT: "INT",
        NFType.VECTOR: "VECTOR",
        NFType.BOOL: "BOOLEAN",
        NFType.GEOMETRY: "GEOMETRY",
        NFType.STRING: "STRING",
        NFType.ROTATION: "ROTATION",
    }.get(false_value.typ)
    if input_type is None:
        raise CompileError(f"L-system switch does not support {false_value.typ}")
    node = _new_node(context, "GeometryNodeSwitch", x, y)
    node.input_type = input_type
    context.group.links.new(condition.socket, _input_socket(node, "Switch"))
    context.group.links.new(false_value.socket, _input_socket(node, "False"))
    context.group.links.new(true_value.socket, _input_socket(node, "True"))
    return context.value(_output_socket(node, "Output"), false_value.typ)



def _as_numeric_value(context, value, x=0, y=0, label="numeric value") -> ExtensionBackendValue:
    """Return one runtime numeric carrier, materializing detached constants when needed."""
    if isinstance(value, ExtensionBackendValue):
        if not _is_number_type(value.typ):
            raise CompileError(f"{label} must be numeric")
        return value
    if type(value) is int:
        return _int_value(context, value, x, y)
    if type(value) is float:
        return _value(context, value, x, y)
    raise CompileError(f"{label} must be numeric")


def rotate_about_axis_runtime(context, vector: ExtensionBackendValue, axis: ExtensionBackendValue, radians_value: ExtensionBackendValue, x=0, y=0) -> ExtensionBackendValue:
    """Build Rodrigues rotation using only physical backend-node primitives."""
    if vector.typ is not NFType.VECTOR or axis.typ is not NFType.VECTOR or not _is_number_type(radians_value.typ):
        raise CompileError("L-system runtime rotation expects Vector, Vector, numeric")
    axis_n = _vector_math(context, "NORMALIZE", [axis], NFType.VECTOR, x, y)
    cosine = _math(context, "COSINE", [radians_value], x + 180, y)
    sine = _math(context, "SINE", [radians_value], x + 180, y - 80)
    one_minus_cosine = _math(context, "SUBTRACT", [_value(context, 1.0, x + 160, y - 160), cosine], x + 360, y - 160)
    term1 = _vector_math(context, "SCALE", [vector, cosine], NFType.VECTOR, x + 360, y)
    cross = _vector_math(context, "CROSS_PRODUCT", [axis_n, vector], NFType.VECTOR, x + 360, y - 80)
    term2 = _vector_math(context, "SCALE", [cross, sine], NFType.VECTOR, x + 540, y - 80)
    dot = _vector_math(context, "DOT_PRODUCT", [axis_n, vector], NFType.FLOAT, x + 360, y - 240)
    projection_scale = _math(context, "MULTIPLY", [dot, one_minus_cosine], x + 540, y - 200)
    term3 = _vector_math(context, "SCALE", [axis_n, projection_scale], NFType.VECTOR, x + 700, y - 200)
    sum12 = _vector_math(context, "ADD", [term1, term2], NFType.VECTOR, x + 720, y)
    return _vector_math(context, "ADD", [sum12, term3], NFType.VECTOR, x + 900, y)

MAX_LSYSTEM_BRANCH_DEPTH = 32


def select_backend_category(analysis):
    """Return the stable internal backend category for an analyzed L-system."""
    if not analysis.angle_is_runtime and not analysis.step_is_runtime:
        return "static"
    if analysis.has_spatial_rotation:
        return "spatial_runtime"
    if analysis.has_branches:
        return "branched_runtime"
    return "branch_free_runtime"


def validate_branch_aware_backend_available(analysis, category: str) -> None:
    """Apply the branch-aware runtime branch-depth materialization budget."""
    if category != "branched_runtime":
        return
    if analysis.max_branch_depth > MAX_LSYSTEM_BRANCH_DEPTH:
        raise CompileError(
            f"L-system branched_runtime backend exceeds MAX_LSYSTEM_BRANCH_DEPTH={MAX_LSYSTEM_BRANCH_DEPTH}"
        )

def _socket_by_name(sockets, name: str, *, node, direction: str):
    """Return one required Blender 5.2 socket by its public name."""
    socket = sockets.get(name)
    if socket is None:
        raise CompileError(
            f"{getattr(node, 'bl_idname', '<node>')} has no {direction} socket {name!r} for the Blender 5.2 contract"
        )
    return socket


def _input_socket(node, name: str):
    return _socket_by_name(node.inputs, name, node=node, direction="input")


def _output_socket(node, name: str):
    return _socket_by_name(node.outputs, name, node=node, direction="output")


def _named_attribute(context, attr_name: str, data_type: str, typ: NFType, x=0, y=0):
    """Read one named attribute through the Blender 5.2 Named Attribute contract."""
    node = _new_node(context, "GeometryNodeInputNamedAttribute", x, y)
    node.data_type = data_type
    _input_socket(node, "Name").default_value = attr_name
    return context.value(_output_socket(node, "Attribute"), typ)


def _accumulate_vector(context, value: ExtensionBackendValue, x=0, y=0):
    """Accumulate a Vector field on Blender 5.2's point domain."""
    if value.typ != NFType.VECTOR:
        raise CompileError("L-system position accumulation expects a Vector field")
    node = _new_node(context, "GeometryNodeAccumulateField", x, y)
    node.data_type = "FLOAT_VECTOR"
    node.domain = "POINT"
    context.group.links.new(value.socket, _input_socket(node, "Value"))
    return context.value(_output_socket(node, "Leading"), NFType.VECTOR)



def _accumulate_vector_grouped(context, value: ExtensionBackendValue, group_id: ExtensionBackendValue, x=0, y=0):
    """Accumulate a Vector field independently for each Blender 5.2 Group ID."""
    if value.typ != NFType.VECTOR or group_id.typ != NFType.INT:
        raise CompileError("L-system grouped accumulation expects Vector value and Int group id")
    node = _new_node(context, "GeometryNodeAccumulateField", x, y)
    node.data_type = "FLOAT_VECTOR"
    node.domain = "POINT"
    context.group.links.new(value.socket, _input_socket(node, "Value"))
    context.group.links.new(group_id.socket, _input_socket(node, "Group ID"))
    return context.value(_output_socket(node, "Leading"), NFType.VECTOR)



def _zero_vector(context, x=0, y=0):
    return _combine_xyz_mixed(context, [0.0, 0.0, 0.0], x, y)


def _store_named_attribute_geometry(context, geometry: ExtensionBackendValue, attr_name: str, value: ExtensionBackendValue, *, selection: ExtensionBackendValue | None = None, domain="POINT", data_type="FLOAT_VECTOR", x=0, y=0):
    """Store one named attribute through the Blender 5.2 socket/property contract."""
    if geometry.typ != NFType.GEOMETRY:
        raise CompileError("Store Named Attribute backend helper received non-geometry")
    node = _new_node(context, "GeometryNodeStoreNamedAttribute", x, y)
    node.data_type = data_type
    node.domain = domain
    context.group.links.new(geometry.socket, _input_socket(node, "Geometry"))
    selection_socket = _input_socket(node, "Selection")
    selection_socket.default_value = True
    if selection is not None:
        if selection.typ != NFType.BOOL:
            raise CompileError("Store Named Attribute selection expects Bool")
        context.group.links.new(selection.socket, selection_socket)
    _input_socket(node, "Name").default_value = attr_name
    context.group.links.new(value.socket, _input_socket(node, "Value"))
    return context.value(_output_socket(node, "Geometry"), NFType.GEOMETRY)



def _sample_index_vector(context, geometry: ExtensionBackendValue, value: ExtensionBackendValue, index: ExtensionBackendValue, x=0, y=0):
    """Sample a Vector field through Blender 5.2 Sample Index."""
    if geometry.typ != NFType.GEOMETRY or value.typ != NFType.VECTOR or index.typ != NFType.INT:
        raise CompileError("Sample Index backend helper received incompatible values")
    node = _new_node(context, "GeometryNodeSampleIndex", x, y)
    node.data_type = "FLOAT_VECTOR"
    node.domain = "POINT"
    context.group.links.new(geometry.socket, _input_socket(node, "Geometry"))
    context.group.links.new(value.socket, _input_socket(node, "Value"))
    context.group.links.new(index.socket, _input_socket(node, "Index"))
    return context.value(_output_socket(node, "Value"), NFType.VECTOR)


def _set_position_geometry(context, geometry: ExtensionBackendValue, position: ExtensionBackendValue, x=0, y=0):
    if geometry.typ != NFType.GEOMETRY or position.typ != NFType.VECTOR:
        raise CompileError("Set Position backend helper received incompatible values")
    node = _new_node(context, "GeometryNodeSetPosition", x, y)
    context.group.links.new(geometry.socket, _input_socket(node, "Geometry"))
    context.group.links.new(position.socket, _input_socket(node, "Position"))
    return context.value(_output_socket(node, "Geometry"), NFType.GEOMETRY)


def _boolean_not(context, value: ExtensionBackendValue, x=0, y=0):
    """Negate one Bool field with Blender 5.2 Boolean Math."""
    if value.typ != NFType.BOOL:
        raise CompileError("Boolean NOT expects Bool")
    node = _new_node(context, "FunctionNodeBooleanMath", x, y)
    node.operation = "NOT"
    context.group.links.new(value.socket, node.inputs[0])
    return context.value(node.outputs[0], NFType.BOOL)



def _delete_edges(context, geometry: ExtensionBackendValue, selection: ExtensionBackendValue, x=0, y=0):
    """Delete selected edges using the Blender 5.2 Delete Geometry contract."""
    if geometry.typ != NFType.GEOMETRY or selection.typ != NFType.BOOL:
        raise CompileError("Delete Geometry backend helper received incompatible values")
    node = _new_node(context, "GeometryNodeDeleteGeometry", x, y)
    node.domain = "EDGE"
    node.mode = "ALL"
    context.group.links.new(geometry.socket, _input_socket(node, "Geometry"))
    context.group.links.new(selection.socket, _input_socket(node, "Selection"))
    return context.value(_output_socket(node, "Geometry"), NFType.GEOMETRY)



def _mesh_to_curve(context, geometry: ExtensionBackendValue, x=0, y=0):
    """Convert selected mesh edges to curves using the Blender 5.2 contract."""
    if geometry.typ != NFType.GEOMETRY:
        raise CompileError("Mesh to Curve backend helper received non-geometry")
    node = _new_node(context, "GeometryNodeMeshToCurve", x, y)
    node.mode = "EDGES"
    context.group.links.new(geometry.socket, _input_socket(node, "Mesh"))
    return context.value(_output_socket(node, "Curve"), NFType.GEOMETRY)



def _scale_float(context, a: ExtensionBackendValue, b: ExtensionBackendValue, x=0, y=0):
    return _math(context, "MULTIPLY", [a, b], x, y)



def _join_geometry_values(context, geos, x=0, y=0):
    """Join multiple geometry values without depending on generic builtin dispatch."""
    geos = [geo for geo in geos if geo is not None]
    if not geos:
        raise CompileError("L-system backend produced no geometry")
    if len(geos) == 1:
        return geos[0]
    node = _new_node(context, "GeometryNodeJoinGeometry", x, y)
    for geo in geos:
        if geo.typ != NFType.GEOMETRY:
            raise CompileError("L-system join helper received non-geometry")
        context.group.links.new(geo.socket, _input_socket(node, "Geometry"))
    return context.value(_output_socket(node, "Geometry"), NFType.GEOMETRY)


def _delete_geometry(context, geometry: ExtensionBackendValue, selection: ExtensionBackendValue, *, domain: str, x=0, y=0):
    """Delete selected geometry elements through Blender 5.2 Delete Geometry."""
    if geometry.typ != NFType.GEOMETRY or selection.typ != NFType.BOOL:
        raise CompileError("Delete Geometry backend helper received incompatible values")
    node = _new_node(context, "GeometryNodeDeleteGeometry", x, y)
    node.domain = domain
    node.mode = "ALL"
    context.group.links.new(geometry.socket, _input_socket(node, "Geometry"))
    context.group.links.new(selection.socket, _input_socket(node, "Selection"))
    return context.value(_output_socket(node, "Geometry"), NFType.GEOMETRY)



def _resolve_numeric_arg(context, static_attr: ExtensionBackendValue, param_index_attr: ExtensionBackendValue, runtime_params, label: str, x=0, y=0):
    """Resolve a point-domain numeric value from static storage plus runtime parameter slots."""
    if static_attr.typ != NFType.FLOAT or param_index_attr.typ != NFType.INT:
        raise CompileError(f"{label} argument resolver received incompatible fields")
    result = static_attr
    for idx, (_name, runtime_value) in enumerate(runtime_params):
        match = _compare(context, "EQUAL", param_index_attr, _int_value(context, idx, x - 160, y - idx * 70), x, y - idx * 70)
        runtime_float = _as_numeric_value(context, runtime_value, x + 40, y - idx * 70, label)
        result = _switch(context, match, result, runtime_float, x + 220, y - idx * 70)
    return result


def _runtime_motion_fields(context, table, source_geo: ExtensionBackendValue, *, x=0, y=0, grouped=False):
    """Build common runtime fields for per-token turn and movement data."""
    move_static = _named_attribute(context, MOVE_DISTANCE_STATIC_ATTR, "FLOAT", NFType.FLOAT, x - 760, y - 120)
    move_index = _named_attribute(context, MOVE_PARAM_INDEX_ATTR, "INT", NFType.INT, x - 760, y - 200)
    turn_static = _named_attribute(context, TURN_DEGREES_STATIC_ATTR, "FLOAT", NFType.FLOAT, x - 760, y - 300)
    turn_index = _named_attribute(context, TURN_PARAM_INDEX_ATTR, "INT", NFType.INT, x - 760, y - 380)
    turn_sign = _named_attribute(context, TURN_SIGN_ATTR, "FLOAT", NFType.FLOAT, x - 760, y - 460)
    draw_mask = _named_attribute(context, DRAW_MASK_ATTR, "BOOLEAN", NFType.BOOL, x + 900, y - 360)

    move_distance = _resolve_numeric_arg(context, move_static, move_index, table.runtime_params, "L-system move", x - 420, y - 120)
    turn_value = _resolve_numeric_arg(context, turn_static, turn_index, table.runtime_params, "L-system turn", x - 420, y - 300)
    runtime_turn = _scale_float(context, turn_sign, turn_value, x - 180, y - 300)
    effective_turn = _math(context, "ADD", [turn_static, runtime_turn], x, y - 300)
    radians = _scale_float(context, effective_turn, _value(context, 3.141592653589793 / 180.0, x, y - 360), x + 180, y - 300)
    if grouped:
        path_id = _named_attribute(context, PATH_ID_ATTR, "INT", NFType.INT, x - 760, y - 540)
        heading = _accumulate_vector_grouped(context, _combine_xyz_mixed(context, [radians, 0.0, 0.0], x + 340, y - 300), path_id, x + 520, y - 300)
        # Reuse vector accumulation to get x component without adding a float grouped helper.
        heading = _separate_xyz(context, heading, "x", x + 700, y - 300)
    else:
        heading = _accumulate_float(context, radians, x + 360, y - 300)
        path_id = None
    cos_heading = _math(context, "COSINE", [heading], x + 520, y - 120)
    sin_heading = _math(context, "SINE", [heading], x + 520, y - 180)
    dx = _scale_float(context, move_distance, cos_heading, x + 700, y - 120)
    dy = _scale_float(context, move_distance, sin_heading, x + 700, y - 180)
    delta = _combine_xyz_mixed(context, [dx, dy, 0.0], x + 880, y - 140)
    tangent = _combine_xyz_mixed(context, [cos_heading, sin_heading, 0.0], x + 880, y - 260)
    return delta, draw_mask, path_id, tangent


def _accumulate_float(context, value: ExtensionBackendValue, x=0, y=0):
    """Accumulate a Float field on Blender 5.2's point domain."""
    if value.typ != NFType.FLOAT:
        raise CompileError("L-system float accumulation expects a Float field")
    node = _new_node(context, "GeometryNodeAccumulateField", x, y)
    node.data_type = "FLOAT"
    node.domain = "POINT"
    context.group.links.new(value.socket, _input_socket(node, "Value"))
    return context.value(_output_socket(node, "Leading"), NFType.FLOAT)



def _store_runtime_marker_orientation(context, geometry: ExtensionBackendValue, tangent: ExtensionBackendValue, up: ExtensionBackendValue | None = None, *, x=0, y=0):
    """Store marker Heading and Up vectors on marker points only."""
    keep_markers = _named_attribute(context, MARKER_MASK_ATTR, "BOOLEAN", NFType.BOOL, x, y)
    result = _store_named_attribute_geometry(context, geometry, MARKER_TANGENT_ATTR, tangent, selection=keep_markers, domain="POINT", data_type="FLOAT_VECTOR", x=x + 220, y=y)
    if up is None:
        up = _combine_xyz_mixed(context, [0.0, 0.0, 1.0], x, y - 80)
    return _store_named_attribute_geometry(context, result, MARKER_UP_ATTR, up, selection=keep_markers, domain="POINT", data_type="FLOAT_VECTOR", x=x + 440, y=y - 80)


def _store_runtime_marker_params(
    context,
    geometry: ExtensionBackendValue,
    *,
    marker_parameter_names,
    runtime_params,
    x=0,
    y=0,
):
    """Apply runtime marker-parameter attributes from explicit package dependencies."""
    result = geometry
    for idx, attr_name in enumerate(marker_parameter_names):
        index_name = f"nf_lsys_marker_param_index_{attr_name}"
        static_attr = _named_attribute(context, attr_name, "FLOAT", NFType.FLOAT, x, y - idx * 150)
        index_attr = _named_attribute(context, index_name, "INT", NFType.INT, x, y - idx * 150 - 60)
        value = _resolve_numeric_arg(
            context, static_attr, index_attr, runtime_params, f"L-system marker parameter {attr_name}", x + 240, y - idx * 150
        )
        result = _store_named_attribute_geometry(
            context, result, attr_name, value, domain="POINT", data_type="FLOAT", x=x + 620, y=y - idx * 150
        )
    return result



def _marker_selection(context, marker_name: str, *, x=0, y=0):
    ids = marker_identity(marker_name)
    selection = _named_attribute(context, MARKER_MASK_ATTR, "BOOLEAN", NFType.BOOL, x, y)
    for idx, (attr_name, wanted) in enumerate(zip(MARKER_ID_ATTRS, ids)):
        attr = _named_attribute(context, attr_name, "INT", NFType.INT, x, y - 80 * (idx + 1))
        eq = _compare(context, "EQUAL", attr, _int_value(context, wanted, x + 200, y - 80 * (idx + 1)), x + 400, y - 80 * (idx + 1))
        selection = _boolean_math(context, "AND", [selection, eq], x + 600, y - 80 * (idx + 1))
    return selection


def filter_marker_points(context, geometry: ExtensionBackendValue, marker_name: str, *, x=0, y=0):
    """Return only point-domain marker geometry matching *marker_name*."""
    if geometry.typ != NFType.GEOMETRY:
        raise CompileError("points() first argument must be Geometry")
    keep = _marker_selection(context, marker_name, x=x - 620, y=y)
    delete = _boolean_not(context, keep, x=x + 40, y=y)
    return _delete_geometry(context, geometry, delete, domain="POINT", x=x + 240, y=y)


def _object_geometry_from_generated(context, obj, *, x=0, y=0):
    """Expose one generated Object as Geometry through Blender 5.2 Object Info."""
    node = _new_node(context, "GeometryNodeObjectInfo", x, y)
    node.transform_space = "ORIGINAL"
    _input_socket(node, "Object").default_value = obj
    return context.value(_output_socket(node, "Geometry"), NFType.GEOMETRY)



def branch_free_vectorized_runtime_backend(context, table, *, angle_degrees, step, x=0, y=0):
    """Materialize branch-free runtime L-systems as a bounded vectorized field graph."""
    if table.draw_count <= 0 and table.marker_count <= 0:
        raise CompileError("Branch-free runtime L-system backend requires at least one drawn F segment")
    from . import resources

    _mesh, obj = resources.create_command_mesh_object_from_table(
        context, table, name_hint=getattr(context.group, "name", "NodeForge")
    )
    source_geo = _object_geometry_from_generated(context, obj, x=x, y=y)
    delta, draw_mask, _, tangent = _runtime_motion_fields(context, table, source_geo, x=x, y=y, grouped=False)
    position = _accumulate_vector(context, delta, x + 1080, y - 140)
    positioned = _set_position_geometry(context, source_geo, position, x + 1280, y)
    positioned = _store_runtime_marker_orientation(context, positioned, tangent, x=x + 1280, y=y - 500)
    positioned = _store_runtime_marker_params(
        context,
        positioned,
        marker_parameter_names=tuple(table.marker_param_static),
        runtime_params=table.runtime_params,
        x=x + 1280,
        y=y - 700,
    )
    geos = []
    if table.draw_count > 0:
        delete_edges = _boolean_not(context, draw_mask, x + 1220, y - 360)
        drawn_edges = _delete_edges(context, positioned, delete_edges, x + 1480, y)
        geos.append(_mesh_to_curve(context, drawn_edges, x + 1680, y))
    if table.marker_count > 0:
        keep_markers = _named_attribute(context, MARKER_MASK_ATTR, "BOOLEAN", NFType.BOOL, x + 1220, y - 620)
        delete_nonmarkers = _boolean_not(context, keep_markers, x + 1420, y - 620)
        geos.append(_delete_geometry(context, positioned, delete_nonmarkers, domain="POINT", x=x + 1680, y=y - 260))
    return _join_geometry_values(context, geos, x + 1900, y)


def branch_aware_vectorized_runtime_backend(context, table, *, angle_degrees, step, x=0, y=0):
    """Materialize branched runtime L-systems as a bounded depth-unrolled field graph."""
    if table.draw_count <= 0 and table.marker_count <= 0:
        raise CompileError("Branch-aware runtime L-system backend requires at least one drawn F segment")
    if table.max_branch_depth > MAX_LSYSTEM_BRANCH_DEPTH:
        raise CompileError(f"L-system branched_runtime backend exceeds MAX_LSYSTEM_BRANCH_DEPTH={MAX_LSYSTEM_BRANCH_DEPTH}")
    from . import resources

    _mesh, obj = resources.create_branch_aware_command_mesh_object_from_table(
        context, table, name_hint=getattr(context.group, "name", "NodeForge")
    )
    source_geo = _object_geometry_from_generated(context, obj, x=x, y=y)
    delta, draw_mask, path_id, tangent = _runtime_motion_fields(context, table, source_geo, x=x, y=y, grouped=True)
    path_depth = _named_attribute(context, PATH_DEPTH_ATTR, "INT", NFType.INT, x - 760, y - 620)
    parent_attach_index = _named_attribute(context, PARENT_ATTACH_INDEX_ATTR, "INT", NFType.INT, x - 760, y - 700)
    local_position = _accumulate_vector_grouped(context, delta, path_id, x + 1080, y - 140)
    geometry = _store_named_attribute_geometry(context, source_geo, LOCAL_POSITION_ATTR, local_position, domain="POINT", data_type="FLOAT_VECTOR", x=x + 1280, y=y - 140)
    root_depth = _compare(context, "EQUAL", path_depth, _int_value(context, 0, x + 1080, y - 620), x + 1280, y - 620)
    safe_parent_attach_index = _switch(context, root_depth, parent_attach_index, _int_value(context, 0, x + 1280, y - 700), x + 1480, y - 700)
    zero = _zero_vector(context, x + 1280, y - 540)
    initial_world = _switch(context, root_depth, zero, local_position, x + 1480, y - 300)
    geometry = _store_named_attribute_geometry(context, geometry, WORLD_POSITION_ATTR, initial_world, domain="POINT", data_type="FLOAT_VECTOR", x=x + 1680, y=y - 160)
    for depth in range(1, table.max_branch_depth + 1):
        row_y = y - 180 - depth * 170
        current_world = _named_attribute(context, WORLD_POSITION_ATTR, "FLOAT_VECTOR", NFType.VECTOR, x + 1500, row_y)
        parent_world = _sample_index_vector(context, geometry, current_world, safe_parent_attach_index, x + 1700, row_y)
        candidate_world = _vector_math(context, "ADD", [parent_world, local_position], NFType.VECTOR, x + 1900, row_y)
        depth_match = _compare(context, "EQUAL", path_depth, _int_value(context, depth, x + 1700, row_y - 70), x + 1900, row_y - 70)
        geometry = _store_named_attribute_geometry(context, geometry, WORLD_POSITION_ATTR, candidate_world, selection=depth_match, domain="POINT", data_type="FLOAT_VECTOR", x=x + 2100, y=row_y)
    final_world = _named_attribute(context, WORLD_POSITION_ATTR, "FLOAT_VECTOR", NFType.VECTOR, x + 2300, y - 120)
    positioned = _set_position_geometry(context, geometry, final_world, x + 2500, y)
    positioned = _store_runtime_marker_orientation(context, positioned, tangent, x=x + 2500, y=y - 500)
    positioned = _store_runtime_marker_params(
        context,
        positioned,
        marker_parameter_names=tuple(table.marker_param_static),
        runtime_params=table.runtime_params,
        x=x + 2500,
        y=y - 700,
    )
    geos = []
    if table.draw_count > 0:
        delete_edges = _boolean_not(context, draw_mask, x + 2440, y - 360)
        drawn_edges = _delete_edges(context, positioned, delete_edges, x + 2700, y)
        geos.append(_mesh_to_curve(context, drawn_edges, x + 2900, y))
    if table.marker_count > 0:
        keep_markers = _named_attribute(context, MARKER_MASK_ATTR, "BOOLEAN", NFType.BOOL, x + 2440, y - 620)
        delete_nonmarkers = _boolean_not(context, keep_markers, x + 2640, y - 620)
        geos.append(_delete_geometry(context, positioned, delete_nonmarkers, domain="POINT", x=x + 2900, y=y - 260))
    return _join_geometry_values(context, geos, x + 3120, y)



def _sample_index_typed(context, geometry: ExtensionBackendValue, value: ExtensionBackendValue, index: ExtensionBackendValue, data_type: str, typ: NFType, x=0, y=0):
    """Sample a typed point-domain field through Blender 5.2 Sample Index."""
    if geometry.typ != NFType.GEOMETRY or index.typ != NFType.INT:
        raise CompileError("Sample Index spatial helper received incompatible geometry/index")
    node = _new_node(context, "GeometryNodeSampleIndex", x, y)
    node.data_type = data_type
    node.domain = "POINT"
    context.group.links.new(geometry.socket, _input_socket(node, "Geometry"))
    context.group.links.new(value.socket, _input_socket(node, "Value"))
    context.group.links.new(index.socket, _input_socket(node, "Index"))
    return context.value(_output_socket(node, "Value"), typ)



def _sample_command_attr(context, source_geo, name, data_type, typ, index, x, y):
    field = _named_attribute(context, name, data_type, typ, x, y)
    return _sample_index_typed(context, source_geo, field, index, data_type, typ, x + 180, y)


def _normalize_vector(context, value: ExtensionBackendValue, x=0, y=0):
    return _vector_math(context, "NORMALIZE", [value], NFType.VECTOR, x, y)


def spatial_runtime_backend(context, table, *, x=0, y=0):
    """Evaluate a spatial turtle sequentially in a Repeat Zone.

    Arbitrary yaw/pitch/roll rotations are non-commutative, so the planar
    accumulated-heading optimization cannot represent them. Each table row
    therefore depends on an already evaluated earlier parent frame.
    """
    if table.draw_count <= 0 and table.marker_count <= 0:
        raise CompileError("Spatial runtime L-system backend requires drawn segments or markers")
    from . import resources

    _mesh, obj = resources.create_spatial_command_mesh_object_from_table(
        context, table, name_hint=getattr(context.group, "name", "NodeForge")
    )
    source_geo = _object_geometry_from_generated(context, obj, x=x, y=y)

    ri = _new_node(context, "GeometryNodeRepeatInput", x + 260, y)
    ro = _new_node(context, "GeometryNodeRepeatOutput", x + 2500, y)
    if not ri.pair_with_output(ro):
        raise CompileError("Could not pair spatial L-system Repeat Zone nodes")
    _input_socket(ri, "Iterations").default_value = table.vertex_count
    context.group.links.new(source_geo.socket, _input_socket(ri, "Geometry"))
    carried = context.value(_output_socket(ri, "Geometry"), NFType.GEOMETRY)
    iteration = context.value(_output_socket(ri, "Iteration"), NFType.INT)

    current_index = iteration
    parent_index = _sample_command_attr(context, source_geo, PARENT_STATE_INDEX_ATTR, "INT", NFType.INT, current_index, x + 420, y - 120)
    command_kind = _sample_command_attr(context, source_geo, COMMAND_KIND_ATTR, "INT", NFType.INT, current_index, x + 420, y - 220)
    value_static = _sample_command_attr(context, source_geo, COMMAND_VALUE_STATIC_ATTR, "FLOAT", NFType.FLOAT, current_index, x + 420, y - 320)
    value_param_index = _sample_command_attr(context, source_geo, COMMAND_VALUE_PARAM_INDEX_ATTR, "INT", NFType.INT, current_index, x + 420, y - 420)
    command_sign = _sample_command_attr(context, source_geo, COMMAND_SIGN_ATTR, "FLOAT", NFType.FLOAT, current_index, x + 420, y - 520)
    value = _resolve_numeric_arg(context, value_static, value_param_index, table.runtime_params, "L-system spatial command", x + 780, y - 340)

    parent_position_field = _named_attribute(context, WORLD_POSITION_ATTR, "FLOAT_VECTOR", NFType.VECTOR, x + 760, y + 40)
    parent_heading_field = _named_attribute(context, HEADING_ATTR, "FLOAT_VECTOR", NFType.VECTOR, x + 760, y - 40)
    parent_left_field = _named_attribute(context, LEFT_ATTR, "FLOAT_VECTOR", NFType.VECTOR, x + 760, y - 120)
    parent_up_field = _named_attribute(context, UP_ATTR, "FLOAT_VECTOR", NFType.VECTOR, x + 760, y - 200)
    parent_position = _sample_index_vector(context, carried, parent_position_field, parent_index, x + 980, y + 40)
    parent_heading = _sample_index_vector(context, carried, parent_heading_field, parent_index, x + 980, y - 40)
    parent_left = _sample_index_vector(context, carried, parent_left_field, parent_index, x + 980, y - 120)
    parent_up = _sample_index_vector(context, carried, parent_up_field, parent_index, x + 980, y - 200)

    radians_value = _math(context, "MULTIPLY", [value, _value(context, 3.141592653589793 / 180.0, x + 980, y - 320)], x + 1160, y - 320)
    signed_radians = _math(context, "MULTIPLY", [radians_value, command_sign], x + 1340, y - 320)

    scaled_heading = _vector_math(context, "SCALE", [parent_heading, value], NFType.VECTOR, x + 1160, y + 140)
    moved_position = _vector_math(context, "ADD", [parent_position, scaled_heading], NFType.VECTOR, x + 1340, y + 140)
    yaw_h = _normalize_vector(context, rotate_about_axis_runtime(context, parent_heading, parent_up, signed_radians, x + 1160, y - 520), x + 2100, y - 500)
    yaw_l = _normalize_vector(context, rotate_about_axis_runtime(context, parent_left, parent_up, signed_radians, x + 1160, y - 700), x + 2100, y - 680)
    pitch_h = _normalize_vector(context, rotate_about_axis_runtime(context, parent_heading, parent_left, signed_radians, x + 1160, y - 880), x + 2100, y - 860)
    pitch_u = _normalize_vector(context, rotate_about_axis_runtime(context, parent_up, parent_left, signed_radians, x + 1160, y - 1060), x + 2100, y - 1040)
    roll_l = _normalize_vector(context, rotate_about_axis_runtime(context, parent_left, parent_heading, signed_radians, x + 1160, y - 1240), x + 2100, y - 1220)
    roll_u = _normalize_vector(context, rotate_about_axis_runtime(context, parent_up, parent_heading, signed_radians, x + 1160, y - 1420), x + 2100, y - 1400)

    is_move_draw = _compare(context, "EQUAL", command_kind, _int_value(context, CMD_MOVE_DRAW, x + 1480, y + 260), x + 1660, y + 260)
    is_move_no_draw = _compare(context, "EQUAL", command_kind, _int_value(context, CMD_MOVE_NO_DRAW, x + 1480, y + 200), x + 1660, y + 200)
    is_move = _boolean_math(context, "OR", [is_move_draw, is_move_no_draw], x + 1840, y + 230)
    is_yaw = _compare(context, "EQUAL", command_kind, _int_value(context, CMD_YAW, x + 1480, y + 100), x + 1660, y + 100)
    is_pitch = _compare(context, "EQUAL", command_kind, _int_value(context, CMD_PITCH, x + 1480, y + 40), x + 1660, y + 40)
    is_roll = _compare(context, "EQUAL", command_kind, _int_value(context, CMD_ROLL, x + 1480, y - 20), x + 1660, y - 20)

    new_position = _switch(context, is_move, parent_position, moved_position, x + 2020, y + 180)
    new_heading = _switch(context, is_yaw, parent_heading, yaw_h, x + 2200, y + 80)
    new_heading = _switch(context, is_pitch, new_heading, pitch_h, x + 2380, y + 80)
    new_left = _switch(context, is_yaw, parent_left, yaw_l, x + 2200, y - 40)
    new_left = _switch(context, is_roll, new_left, roll_l, x + 2380, y - 40)
    new_up = _switch(context, is_pitch, parent_up, pitch_u, x + 2200, y - 160)
    new_up = _switch(context, is_roll, new_up, roll_u, x + 2380, y - 160)

    index_node = _new_node(context, "GeometryNodeInputIndex", x + 1960, y + 360)
    point_index = context.value(index_node.outputs[0], NFType.INT)
    current_selection = _compare(context, "EQUAL", point_index, current_index, x + 2140, y + 360)
    state_geo = _store_named_attribute_geometry(context, carried, WORLD_POSITION_ATTR, new_position, selection=current_selection, domain="POINT", data_type="FLOAT_VECTOR", x=x + 2580, y=y + 140)
    state_geo = _store_named_attribute_geometry(context, state_geo, HEADING_ATTR, new_heading, selection=current_selection, domain="POINT", data_type="FLOAT_VECTOR", x=x + 2780, y=y + 60)
    state_geo = _store_named_attribute_geometry(context, state_geo, LEFT_ATTR, new_left, selection=current_selection, domain="POINT", data_type="FLOAT_VECTOR", x=x + 2980, y=y - 20)
    state_geo = _store_named_attribute_geometry(context, state_geo, UP_ATTR, new_up, selection=current_selection, domain="POINT", data_type="FLOAT_VECTOR", x=x + 3180, y=y - 100)
    context.group.links.new(state_geo.socket, _input_socket(ro, "Geometry"))
    repeated = context.value(_output_socket(ro, "Geometry"), NFType.GEOMETRY)

    final_world = _named_attribute(context, WORLD_POSITION_ATTR, "FLOAT_VECTOR", NFType.VECTOR, x + 3400, y + 120)
    final_heading = _named_attribute(context, HEADING_ATTR, "FLOAT_VECTOR", NFType.VECTOR, x + 3400, y + 40)
    final_up = _named_attribute(context, UP_ATTR, "FLOAT_VECTOR", NFType.VECTOR, x + 3400, y - 40)
    positioned = _set_position_geometry(context, repeated, final_world, x + 3600, y + 120)
    positioned = _store_runtime_marker_orientation(context, positioned, final_heading, final_up, x=x + 3600, y=y - 80)
    positioned = _store_runtime_marker_params(
        context,
        positioned,
        marker_parameter_names=tuple(table.marker_param_static),
        runtime_params=table.runtime_params,
        x=x + 3800,
        y=y - 300,
    )

    geos = []
    if table.draw_count > 0:
        draw_mask = _named_attribute(context, DRAW_MASK_ATTR, "BOOLEAN", NFType.BOOL, x + 4000, y + 120)
        delete_edges = _boolean_not(context, draw_mask, x + 4180, y + 120)
        drawn_edges = _delete_edges(context, positioned, delete_edges, x + 4360, y + 120)
        geos.append(_mesh_to_curve(context, drawn_edges, x + 4540, y + 120))
    if table.marker_count > 0:
        keep_markers = _named_attribute(context, MARKER_MASK_ATTR, "BOOLEAN", NFType.BOOL, x + 4000, y - 120)
        delete_nonmarkers = _boolean_not(context, keep_markers, x + 4180, y - 120)
        geos.append(_delete_geometry(context, positioned, delete_nonmarkers, domain="POINT", x=x + 4360, y=y - 120))
    return _join_geometry_values(context, geos, x + 4760, y)

def static_baked_backend(context, interpretation, x=0, y=0):
    """Materialize static turtle segments and marker points as generated IDs."""
    segments = getattr(interpretation, "segments", interpretation)
    markers = getattr(interpretation, "markers", ())
    if not segments and not markers:
        raise CompileError("Static L-system backend requires at least one drawn F segment")
    from . import resources

    geos = []
    if segments:
        _curve, obj = resources.create_curve_object_from_segments(
            context, segments, name_hint=getattr(context.group, "name", "NodeForge")
        )
        geos.append(_object_geometry_from_generated(context, obj, x=x, y=y))
    if markers:
        _mesh, obj, runtime_slots = resources.create_marker_mesh_object_from_points(
            context, markers, name_hint=getattr(context.group, "name", "NodeForge")
        )
        marker_geo = _object_geometry_from_generated(context, obj, x=x, y=y - 180)
        marker_geo = _store_runtime_marker_params(
            context,
            marker_geo,
            marker_parameter_names=tuple(sorted({name for marker in markers for name in marker.parameters})),
            runtime_params=runtime_slots,
            x=x + 260,
            y=y - 360,
        )
        geos.append(marker_geo)
    return _join_geometry_values(context, geos, x + 260, y)


__all__ = [
    "MAX_LSYSTEM_BRANCH_DEPTH", "select_backend_category", "validate_branch_aware_backend_available",
    "static_baked_backend", "branch_free_vectorized_runtime_backend", "branch_aware_vectorized_runtime_backend", "spatial_runtime_backend", "filter_marker_points",
]
