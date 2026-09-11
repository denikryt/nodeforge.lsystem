"""Runtime L-system rewriting and stream-sized spatial turtle backend.

This module owns the topology-dynamic path used when ``ls_iterations`` receives
an Int ``Value``. Grammar resources remain compile-time sized, while the active
L-string and branch stack are variable-size Geometry Nodes data.
"""

from __future__ import annotations

from dataclasses import dataclass

from NodeForge.constants import TYPE_BOOL, TYPE_FLOAT, TYPE_GEOMETRY, TYPE_INT, TYPE_ROTATION, TYPE_VECTOR
from NodeForge.errors import CompileError
from NodeForge.nodes import _boolean_math, _combine_xyz_mixed, _int_value, _new_node, _switch, _value, _vector_math
from NodeForge.values import Value

from . import resources
from .backends import (
    _input_socket,
    _join_geometry_values,
    _named_attribute,
    _object_geometry_from_generated,
    _output_socket,
    _resolve_numeric_arg,
    _sample_index_typed,
    _set_enum,
    _socket_by_name,
    _store_named_attribute_geometry,
    _store_runtime_marker_params,
)
from .model import LSystemModule, LSystemSpec
from .runtime_tables import (
    COMMAND_KIND_ATTR,
    COMMAND_SIGN_ATTR,
    COMMAND_VALUE_PARAM_INDEX_ATTR,
    COMMAND_VALUE_STATIC_ATTR,
    DRAW_MASK_ATTR,
    MARKER_DEPTH_ATTR,
    MARKER_ID_ATTRS,
    MARKER_ITERATION_ATTR,
    MARKER_MASK_ATTR,
    MARKER_PATH_ID_ATTR,
    MARKER_TANGENT_ATTR,
    MARKER_UP_ATTR,
    CMD_INITIAL,
    CMD_MOVE_DRAW,
    CMD_MOVE_NO_DRAW,
    CMD_PITCH,
    CMD_POP,
    CMD_PUSH,
    CMD_ROLL,
    CMD_YAW,
    encode_command_fields,
    encode_marker_payload,
)
from .validation import validate_runtime_branch_grammar

SYMBOL_ID_ATTR = "nf_lsys_symbol_id"
MODULE_REF_ATTR = "nf_lsys_module_ref"
RULE_HAS_RULE_ATTR = "nf_lsys_rule_has_rule"
RULE_SUCCESSOR_START_ATTR = "nf_lsys_rule_successor_start"
RULE_SUCCESSOR_COUNT_ATTR = "nf_lsys_rule_successor_count"
SEGMENT_START_ATTR = "nf_lsys_segment_start"
ROTATION_ATTR = "nf_lsys_rotation"
STACK_ROTATION_ATTR = "nf_lsys_stack_rotation"
STACK_PATH_ID_ATTR = "nf_lsys_stack_path_id"
STACK_DEPTH_ATTR = "nf_lsys_stack_branch_depth"


@dataclass(frozen=True)
class RuntimeStringTable:
    """Point-only runtime L-string rows storing immutable module references."""

    vertices: tuple[tuple[float, float, float], ...]
    edges: tuple[tuple[int, int], ...]
    module_ref: tuple[int, ...]

    def point_attributes(self):
        """Return the single runtime-string point attribute."""
        return ((MODULE_REF_ATTR, "INT", self.module_ref),)


@dataclass(frozen=True)
class RuntimeModuleDefinitionsTable:
    """Immutable descriptors addressed by ``module_ref`` from runtime strings."""

    vertices: tuple[tuple[float, float, float], ...]
    edges: tuple[tuple[int, int], ...]
    symbol_id: tuple[int, ...]
    command_kind: tuple[int, ...]
    value_static: tuple[float, ...]
    value_param_index: tuple[int, ...]
    command_sign: tuple[float, ...]
    draw_mask: tuple[bool, ...]
    marker_id: tuple[tuple[int, int, int, int], ...]
    marker_mask: tuple[bool, ...]
    marker_iteration: tuple[int, ...]
    marker_param_static: dict[str, tuple[float, ...]]
    marker_param_index: dict[str, tuple[int, ...]]

    def point_attributes(self):
        """Return Blender point attributes for immutable module descriptors."""
        specs = [
            (SYMBOL_ID_ATTR, "INT", self.symbol_id),
            (COMMAND_KIND_ATTR, "INT", self.command_kind),
            (COMMAND_VALUE_STATIC_ATTR, "FLOAT", self.value_static),
            (COMMAND_VALUE_PARAM_INDEX_ATTR, "INT", self.value_param_index),
            (COMMAND_SIGN_ATTR, "FLOAT", self.command_sign),
            (DRAW_MASK_ATTR, "BOOLEAN", self.draw_mask),
            (MARKER_ID_ATTRS[0], "INT", tuple(item[0] for item in self.marker_id)),
            (MARKER_ID_ATTRS[1], "INT", tuple(item[1] for item in self.marker_id)),
            (MARKER_ID_ATTRS[2], "INT", tuple(item[2] for item in self.marker_id)),
            (MARKER_ID_ATTRS[3], "INT", tuple(item[3] for item in self.marker_id)),
            (MARKER_MASK_ATTR, "BOOLEAN", self.marker_mask),
            (MARKER_ITERATION_ATTR, "INT", self.marker_iteration),
        ]
        for name, values in self.marker_param_static.items():
            specs.append((name, "FLOAT", values))
            specs.append((f"nf_lsys_marker_param_index_{name}", "INT", self.marker_param_index[name]))
        return tuple(specs)


@dataclass(frozen=True)
class RuntimeRuleIndexTable:
    """Compact symbol-id indexed production metadata table."""

    vertices: tuple[tuple[float, float, float], ...]
    edges: tuple[tuple[int, int], ...]
    has_rule: tuple[bool, ...]
    successor_start: tuple[int, ...]
    successor_count: tuple[int, ...]

    def point_attributes(self):
        """Return Blender point-attribute specs for production lookup."""
        return (
            (RULE_HAS_RULE_ATTR, "BOOLEAN", self.has_rule),
            (RULE_SUCCESSOR_START_ATTR, "INT", self.successor_start),
            (RULE_SUCCESSOR_COUNT_ATTR, "INT", self.successor_count),
        )


@dataclass(frozen=True)
class RuntimeGrammarEncoding:
    """Compile-time grammar encoding plus shared runtime numeric slots."""

    axiom: RuntimeStringTable
    successors: RuntimeStringTable
    module_definitions: RuntimeModuleDefinitionsTable
    rule_index: RuntimeRuleIndexTable
    runtime_params: tuple[tuple[str, Value], ...]
    marker_parameter_names: tuple[str, ...]



def _known_symbols(spec: LSystemSpec) -> tuple[str, ...]:
    """Return deterministic module names participating in one compiled grammar."""
    names = {module.name for module in spec.axiom}
    names.update(spec.rules)
    for replacement in spec.rules.values():
        names.update(module.name for module in replacement)
    names.update(spec.markers)
    return tuple(sorted(names))


def _module_descriptor_key(module: LSystemModule) -> tuple[str, str]:
    """Return a deterministic key for one immutable parsed module descriptor."""
    return module.name, module.raw or module.name


def _encode_module_definitions(modules, *, spec, symbol_ids, runtime_slots, marker_parameter_names) -> RuntimeModuleDefinitionsTable:
    """Encode unique parsed module descriptors into one immutable lookup table."""
    symbol_values = []
    kinds = []
    statics = []
    param_indexes = []
    signs = []
    draws = []
    marker_ids = []
    marker_masks = []
    marker_iterations = []
    marker_param_static = {name: [] for name in marker_parameter_names}
    marker_param_index = {name: [] for name in marker_parameter_names}

    for module in modules:
        kind, static, param_index, sign = encode_command_fields(
            module, angle_degrees=spec.angle, step=spec.step, markers=spec.markers, runtime_slots=runtime_slots,
        )
        marker_id, marker_mask, marker_iteration, m_static, m_index = encode_marker_payload(
            module, markers=spec.markers, runtime_slots=runtime_slots, parameter_names=marker_parameter_names,
        )
        symbol_values.append(symbol_ids[module.name])
        kinds.append(kind); statics.append(static); param_indexes.append(param_index); signs.append(sign)
        draws.append(kind == CMD_MOVE_DRAW); marker_ids.append(marker_id); marker_masks.append(marker_mask)
        marker_iterations.append(marker_iteration)
        for name in marker_parameter_names:
            marker_param_static[name].append(m_static[name]); marker_param_index[name].append(m_index[name])

    count = len(symbol_values)
    return RuntimeModuleDefinitionsTable(
        vertices=tuple((0.0, 0.0, 0.0) for _ in range(count)), edges=(),
        symbol_id=tuple(symbol_values), command_kind=tuple(kinds), value_static=tuple(statics),
        value_param_index=tuple(param_indexes), command_sign=tuple(signs), draw_mask=tuple(draws),
        marker_id=tuple(marker_ids), marker_mask=tuple(marker_masks), marker_iteration=tuple(marker_iterations),
        marker_param_static={name: tuple(values) for name, values in marker_param_static.items()},
        marker_param_index={name: tuple(values) for name, values in marker_param_index.items()},
    )


def _encode_string_rows(modules, module_refs) -> RuntimeStringTable:
    """Encode one runtime string as point rows containing only module references."""
    refs = tuple(module_refs[_module_descriptor_key(module)] for module in modules)
    return RuntimeStringTable(vertices=tuple((0.0, 0.0, 0.0) for _ in refs), edges=(), module_ref=refs)


def encode_runtime_grammar(spec: LSystemSpec) -> RuntimeGrammarEncoding:
    """Encode runtime strings as refs plus one immutable module descriptor table."""
    validate_runtime_branch_grammar(spec.axiom, spec.rules)
    symbols = _known_symbols(spec)
    symbol_ids = {name: index for index, name in enumerate(symbols)}
    marker_parameter_names = tuple(sorted({name for marker in spec.markers.values() for name in marker.parameter_names}))
    runtime_slots: list[tuple[str, Value]] = []

    all_modules = list(spec.axiom)
    for replacement in spec.rules.values():
        all_modules.extend(replacement)
    unique_modules = []
    module_refs = {}
    for module in all_modules:
        key = _module_descriptor_key(module)
        if key not in module_refs:
            module_refs[key] = len(unique_modules)
            unique_modules.append(module)

    module_definitions = _encode_module_definitions(
        unique_modules, spec=spec, symbol_ids=symbol_ids, runtime_slots=runtime_slots,
        marker_parameter_names=marker_parameter_names,
    )
    axiom = _encode_string_rows(spec.axiom, module_refs)

    successor_modules: list[LSystemModule] = []
    starts = [0] * len(symbols); counts = [0] * len(symbols); has_rule = [False] * len(symbols)
    for symbol in symbols:
        sid = symbol_ids[symbol]; starts[sid] = len(successor_modules)
        replacement = spec.rules.get(symbol)
        if replacement is None:
            continue
        has_rule[sid] = True; counts[sid] = len(replacement); successor_modules.extend(replacement)
    successors = _encode_string_rows(successor_modules, module_refs)
    rule_index = RuntimeRuleIndexTable(
        vertices=tuple((0.0, 0.0, 0.0) for _ in symbols), edges=(),
        has_rule=tuple(has_rule), successor_start=tuple(starts), successor_count=tuple(counts),
    )
    return RuntimeGrammarEncoding(
        axiom=axiom, successors=successors, module_definitions=module_definitions, rule_index=rule_index,
        runtime_params=tuple(runtime_slots), marker_parameter_names=marker_parameter_names,
    )


def _int_math(group, operation: str, left: Value, right: Value, x=0, y=0) -> Value:
    """Create integer-safe Geometry Nodes arithmetic without float coercion."""
    if left.typ != TYPE_INT or right.typ != TYPE_INT:
        raise CompileError("L-system integer math expects Int values")
    node = _new_node(group, "FunctionNodeIntegerMath", x, y)
    node.operation = operation
    group.links.new(left.socket, node.inputs[0])
    group.links.new(right.socket, node.inputs[1])
    return Value(node.outputs[0], TYPE_INT)


def _active_int_compare_input(node, name: str):
    """Return the active integer A/B socket across Blender compare-node layouts."""
    candidates = [
        socket
        for socket in node.inputs
        if getattr(socket, "name", "") == name
        and getattr(socket, "bl_idname", "") == "NodeSocketInt"
        and getattr(socket, "enabled", True)
    ]
    if len(candidates) == 1:
        return candidates[0]

    # Blender 5.2 exposes only the active A/B sockets after data_type is set,
    # while Blender 5.1 keeps inactive sockets from the other compare modes.
    candidates = [
        socket
        for socket in node.inputs
        if getattr(socket, "name", "") == name
        and getattr(socket, "enabled", True)
    ]
    if len(candidates) == 1:
        return candidates[0]
    raise CompileError(f"FunctionNodeCompare has no unique active Int input {name!r} in this Blender runtime")


def _compare_int(group, operation: str, left: Value, right: Value, x=0, y=0) -> Value:
    """Create an integer comparison used by symbol and stack invariants."""
    if left.typ != TYPE_INT or right.typ != TYPE_INT:
        raise CompileError("L-system integer comparison expects Int values")
    node = _new_node(group, "FunctionNodeCompare", x, y)
    node.data_type = "INT"
    node.operation = operation
    group.links.new(left.socket, _active_int_compare_input(node, "A"))
    group.links.new(right.socket, _active_int_compare_input(node, "B"))
    return Value(node.outputs[0], TYPE_BOOL)


def _switch_rotation(group, condition: Value, false_value: Value, true_value: Value, x=0, y=0) -> Value:
    """Select between native Blender Rotation values."""
    if condition.typ != TYPE_BOOL or false_value.typ != TYPE_ROTATION or true_value.typ != TYPE_ROTATION:
        raise CompileError("L-system rotation switch expects Bool and Rotation values")
    node = _new_node(group, "GeometryNodeSwitch", x, y)
    node.input_type = "ROTATION"
    group.links.new(condition.socket, _input_socket(node, "Switch"))
    group.links.new(false_value.socket, _input_socket(node, "False"))
    group.links.new(true_value.socket, _input_socket(node, "True"))
    return Value(_output_socket(node, "Output"), TYPE_ROTATION)


def _identity_rotation(group, x=0, y=0) -> Value:
    """Create the identity native Blender Rotation."""
    node = _new_node(group, "FunctionNodeEulerToRotation", x, y)
    return Value(_output_socket(node, "Rotation"), TYPE_ROTATION)


def _axis_angle_rotation(group, axis, angle: Value, x=0, y=0) -> Value:
    """Create a native Rotation from a local canonical axis and runtime angle."""
    node = _new_node(group, "FunctionNodeAxisAngleToRotation", x, y)
    if isinstance(axis, Value):
        group.links.new(axis.socket, _input_socket(node, "Axis"))
    else:
        _input_socket(node, "Axis").default_value = tuple(axis)
    group.links.new(angle.socket, _input_socket(node, "Angle"))
    return Value(_output_socket(node, "Rotation"), TYPE_ROTATION)


def _compose_rotation(group, rotation: Value, rotate_by: Value, x=0, y=0) -> Value:
    """Compose the turtle orientation with one local-axis delta rotation."""
    node = _new_node(group, "FunctionNodeRotateRotation", x, y)
    group.links.new(rotate_by.socket, _input_socket(node, "Rotation"))
    group.links.new(rotation.socket, _input_socket(node, "Rotate By"))
    return Value(_output_socket(node, "Rotation"), TYPE_ROTATION)


def _rotate_vector_native(group, vector, rotation: Value, x=0, y=0) -> Value:
    """Rotate a vector by a native Blender Rotation."""
    node = _new_node(group, "FunctionNodeRotateVector", x, y)
    if isinstance(vector, Value):
        group.links.new(vector.socket, _input_socket(node, "Vector"))
    else:
        _input_socket(node, "Vector").default_value = tuple(vector)
    group.links.new(rotation.socket, _input_socket(node, "Rotation"))
    return Value(_output_socket(node, "Vector"), TYPE_VECTOR)


def _sample_attr(group, geometry: Value, name: str, data_type: str, typ: str, index: Value, x=0, y=0) -> Value:
    """Sample one named point attribute at an explicit integer index."""
    field = _named_attribute(group, name, data_type, typ, x, y)
    return _sample_index_typed(group, geometry, field, index, data_type, typ, x + 180, y)


def _domain_point_count(group, geometry: Value, x=0, y=0) -> Value:
    """Return the runtime point count of mesh geometry as an Int field."""
    node = _new_node(group, "GeometryNodeAttributeDomainSize", x, y)
    node.component = "MESH"
    group.links.new(geometry.socket, _input_socket(node, "Geometry"))
    return Value(_output_socket(node, "Point Count"), TYPE_INT)


def _duplicate_points(group, geometry: Value, amount: Value, x=0, y=0):
    """Duplicate point-domain modules by per-point successor cardinality."""
    node = _new_node(group, "GeometryNodeDuplicateElements", x, y)
    node.domain = "POINT"
    group.links.new(geometry.socket, _input_socket(node, "Geometry"))
    group.links.new(amount.socket, _input_socket(node, "Amount"))
    return Value(_output_socket(node, "Geometry"), TYPE_GEOMETRY), Value(_output_socket(node, "Duplicate Index"), TYPE_INT)


def _separate_points(group, geometry: Value, selection: Value, x=0, y=0) -> tuple[Value, Value]:
    """Split point geometry into selected and inverted outputs."""
    node = _new_node(group, "GeometryNodeSeparateGeometry", x, y)
    node.domain = "POINT"
    group.links.new(geometry.socket, _input_socket(node, "Geometry"))
    group.links.new(selection.socket, _input_socket(node, "Selection"))
    return Value(_output_socket(node, "Selection"), TYPE_GEOMETRY), Value(_output_socket(node, "Inverted"), TYPE_GEOMETRY)


def _empty_geometry_from(group, geometry: Value, x=0, y=0) -> Value:
    """Create empty point geometry by deleting all points from a seed geometry."""
    node = _new_node(group, "GeometryNodeDeleteGeometry", x, y)
    node.domain = "POINT"
    _input_socket(node, "Selection").default_value = True
    group.links.new(geometry.socket, _input_socket(node, "Geometry"))
    return Value(_output_socket(node, "Geometry"), TYPE_GEOMETRY)


def _single_point(group, position: Value, x=0, y=0) -> Value:
    """Create one mesh point at the supplied runtime position."""
    node = _new_node(group, "GeometryNodeMeshLine", x, y)
    node.mode = "OFFSET"
    _input_socket(node, "Count").default_value = 1
    group.links.new(position.socket, _input_socket(node, "Start Location"))
    return Value(_output_socket(node, "Mesh"), TYPE_GEOMETRY)


def _capture_rewrite_metadata(
    group, geometry: Value, has_rule: Value, successor_start: Value, x=0, y=0
) -> tuple[Value, Value, Value]:
    """Capture predecessor rule metadata as anonymous point attributes.

    The captured fields are evaluated on generation-N geometry before any
    successor payload is written, then propagated through Duplicate Elements.
    This preserves parallel L-system rewrite semantics without temporary named
    attributes or cleanup nodes.
    """
    node = _new_node(group, "GeometryNodeCaptureAttribute", x, y)
    node.domain = "POINT"
    node.capture_items.new("BOOLEAN", "Has Rule")
    node.capture_items.new("INT", "Successor Start")
    group.links.new(geometry.socket, _input_socket(node, "Geometry"))
    group.links.new(has_rule.socket, _input_socket(node, "Has Rule"))
    group.links.new(successor_start.socket, _input_socket(node, "Successor Start"))
    return (
        Value(_output_socket(node, "Geometry"), TYPE_GEOMETRY),
        Value(_output_socket(node, "Has Rule"), TYPE_BOOL),
        Value(_output_socket(node, "Successor Start"), TYPE_INT),
    )


def _rewrite_once(group, current: Value, successor_geo: Value, rule_index_geo: Value, module_def_geo: Value, x=0, y=0) -> Value:
    """Build one parallel derivation while copying only a single ``module_ref``."""
    predecessor_ref = _named_attribute(group, MODULE_REF_ATTR, "INT", TYPE_INT, x, y)
    predecessor_symbol = _sample_attr(group, module_def_geo, SYMBOL_ID_ATTR, "INT", TYPE_INT, predecessor_ref, x + 180, y)
    has_rule = _sample_attr(group, rule_index_geo, RULE_HAS_RULE_ATTR, "BOOLEAN", TYPE_BOOL, predecessor_symbol, x + 360, y + 100)
    successor_start = _sample_attr(group, rule_index_geo, RULE_SUCCESSOR_START_ATTR, "INT", TYPE_INT, predecessor_symbol, x + 360, y)
    successor_count = _sample_attr(group, rule_index_geo, RULE_SUCCESSOR_COUNT_ATTR, "INT", TYPE_INT, predecessor_symbol, x + 360, y - 100)

    captured, rewrite_has_rule, rewrite_start = _capture_rewrite_metadata(
        group, current, has_rule, successor_start, x + 600, y + 60
    )
    amount = _switch(group, has_rule, _int_value(group, 1, x + 600, y - 180), successor_count, x + 800, y - 160)
    duplicated, duplicate_index = _duplicate_points(group, captured, amount, x + 1000, y)

    successor_row = _int_math(group, "ADD", rewrite_start, duplicate_index, x + 1200, y + 40)
    successor_ref = _sample_attr(group, successor_geo, MODULE_REF_ATTR, "INT", TYPE_INT, successor_row, x + 1380, y)
    return _store_named_attribute_geometry(
        group, duplicated, MODULE_REF_ATTR, successor_ref, selection=rewrite_has_rule, domain="POINT", data_type="INT", x=x + 1560, y=y,
    )


def _runtime_rewrite(group, axiom_geo: Value, successor_geo: Value, rule_index_geo: Value, module_def_geo: Value, iterations: Value, x=0, y=0) -> Value:
    """Repeat the parallel rewrite step for a runtime non-negative count."""
    is_negative = _compare_int(group, "LESS_THAN", iterations, _int_value(group, 0, x, y + 140), x + 180, y + 140)
    safe_iterations = _switch(group, is_negative, iterations, _int_value(group, 0, x + 180, y + 80), x + 360, y + 120)

    ri = _new_node(group, "GeometryNodeRepeatInput", x + 520, y)
    ro = _new_node(group, "GeometryNodeRepeatOutput", x + 3600, y)
    if not ri.pair_with_output(ro):
        raise CompileError("Could not pair runtime L-system derivation Repeat Zone nodes")
    group.links.new(safe_iterations.socket, _input_socket(ri, "Iterations"))
    group.links.new(axiom_geo.socket, _input_socket(ri, "Geometry"))
    current = Value(_output_socket(ri, "Geometry"), TYPE_GEOMETRY)
    next_geo = _rewrite_once(group, current, successor_geo, rule_index_geo, module_def_geo, x + 760, y)
    group.links.new(next_geo.socket, _input_socket(ro, "Geometry"))
    return Value(_output_socket(ro, "Geometry"), TYPE_GEOMETRY)


def _add_repeat_item(ro, socket_type: str, name: str):
    """Add one explicit state item to a Blender Repeat Output node."""
    try:
        ro.repeat_items.new(socket_type, name)
    except Exception as exc:
        raise CompileError(f"Could not add runtime L-system Repeat state {name!r}") from exc


def _repeat_state(ri, name: str, typ: str) -> Value:
    """Wrap a Repeat Input state output as a NodeForge Value."""
    return Value(_output_socket(ri, name), typ)


def _repeat_output(ro, name: str, typ: str) -> Value:
    """Wrap a Repeat Output state socket as a NodeForge Value."""
    return Value(_output_socket(ro, name), typ)


def _store_current_row(group, geometry: Value, iteration: Value, name: str, value: Value, data_type: str, x=0, y=0) -> Value:
    """Write one evaluated state field only onto the current module row."""
    index_node = _new_node(group, "GeometryNodeInputIndex", x, y + 100)
    point_index = Value(index_node.outputs[0], TYPE_INT)
    selection = _compare_int(group, "EQUAL", point_index, iteration, x + 160, y + 100)
    return _store_named_attribute_geometry(group, geometry, name, value, selection=selection, domain="POINT", data_type=data_type, x=x + 340, y=y)


def _set_current_row_position(group, geometry: Value, iteration: Value, position: Value, x=0, y=0) -> Value:
    """Write the evaluated turtle position into the current runtime-string point."""
    index_node = _new_node(group, "GeometryNodeInputIndex", x, y + 100)
    point_index = Value(index_node.outputs[0], TYPE_INT)
    selection = _compare_int(group, "EQUAL", point_index, iteration, x + 160, y + 100)
    node = _new_node(group, "GeometryNodeSetPosition", x + 340, y)
    group.links.new(geometry.socket, _input_socket(node, "Geometry"))
    group.links.new(selection.socket, _input_socket(node, "Selection"))
    group.links.new(position.socket, _input_socket(node, "Position"))
    return Value(_output_socket(node, "Geometry"), TYPE_GEOMETRY)


def _sample_stack_rotation(group, stack: Value, x=0, y=0) -> Value:
    """Sample the native Rotation from the unique selected branch-stack frame."""
    return _sample_attr(group, stack, STACK_ROTATION_ATTR, "QUATERNION", TYPE_ROTATION, _int_value(group, 0, x, y - 40), x + 100, y)


def _dynamic_turtle(group, final_string: Value, module_def_geo: Value, encoding: RuntimeGrammarEncoding, x=0, y=0) -> Value:
    """Interpret a variable-length L-string using native Blender Rotation state."""
    count = _domain_point_count(group, final_string, x, y + 360)
    initial_stack = _empty_geometry_from(group, final_string, x, y + 240)
    initial_position = _combine_xyz_mixed(group, [0.0, 0.0, 0.0], x, y + 160)
    initial_rotation = _identity_rotation(group, x, y + 80)

    ri = _new_node(group, "GeometryNodeRepeatInput", x + 280, y)
    ro = _new_node(group, "GeometryNodeRepeatOutput", x + 3900, y)
    if not ri.pair_with_output(ro):
        raise CompileError("Could not pair dynamic L-system turtle Repeat Zone nodes")
    for item in list(ro.repeat_items):
        ro.repeat_items.remove(item)
    for socket_type, name in (
        ("GEOMETRY", "State Geometry"), ("GEOMETRY", "Branch Stack Geometry"),
        ("VECTOR", "Position"), ("ROTATION", "Rotation"),
        ("INT", "Branch Depth"), ("INT", "Path ID"), ("INT", "Next Path ID"),
    ):
        _add_repeat_item(ro, socket_type, name)

    group.links.new(count.socket, _input_socket(ri, "Iterations"))
    initial_values = {
        "State Geometry": final_string, "Branch Stack Geometry": initial_stack,
        "Position": initial_position, "Rotation": initial_rotation,
        "Branch Depth": _int_value(group, 0, x + 100, y - 180),
        "Path ID": _int_value(group, 0, x + 100, y - 240),
        "Next Path ID": _int_value(group, 1, x + 100, y - 300),
    }
    for name, value in initial_values.items():
        group.links.new(value.socket, _input_socket(ri, name))

    state_geo = _repeat_state(ri, "State Geometry", TYPE_GEOMETRY)
    stack = _repeat_state(ri, "Branch Stack Geometry", TYPE_GEOMETRY)
    position = _repeat_state(ri, "Position", TYPE_VECTOR)
    rotation = _repeat_state(ri, "Rotation", TYPE_ROTATION)
    branch_depth = _repeat_state(ri, "Branch Depth", TYPE_INT)
    path_id = _repeat_state(ri, "Path ID", TYPE_INT)
    next_path_id = _repeat_state(ri, "Next Path ID", TYPE_INT)
    iteration = Value(_output_socket(ri, "Iteration"), TYPE_INT)

    module_ref = _sample_attr(group, final_string, MODULE_REF_ATTR, "INT", TYPE_INT, iteration, x + 620, y + 320)
    kind = _sample_attr(group, module_def_geo, COMMAND_KIND_ATTR, "INT", TYPE_INT, module_ref, x + 800, y + 260)
    static = _sample_attr(group, module_def_geo, COMMAND_VALUE_STATIC_ATTR, "FLOAT", TYPE_FLOAT, module_ref, x + 800, y + 180)
    param_index = _sample_attr(group, module_def_geo, COMMAND_VALUE_PARAM_INDEX_ATTR, "INT", TYPE_INT, module_ref, x + 800, y + 100)
    sign = _sample_attr(group, module_def_geo, COMMAND_SIGN_ATTR, "FLOAT", TYPE_FLOAT, module_ref, x + 800, y + 20)
    value = _resolve_numeric_arg(group, static, param_index, encoding.runtime_params, "Dynamic L-system command", x + 1040, y + 160)

    is_move_draw = _compare_int(group, "EQUAL", kind, _int_value(group, CMD_MOVE_DRAW, x + 1080, y + 340), x + 1260, y + 340)
    is_move_nodraw = _compare_int(group, "EQUAL", kind, _int_value(group, CMD_MOVE_NO_DRAW, x + 1080, y + 300), x + 1260, y + 300)
    is_move = _boolean_math(group, "OR", [is_move_draw, is_move_nodraw], x + 1440, y + 320)
    is_yaw = _compare_int(group, "EQUAL", kind, _int_value(group, CMD_YAW, x + 1080, y + 240), x + 1260, y + 240)
    is_pitch = _compare_int(group, "EQUAL", kind, _int_value(group, CMD_PITCH, x + 1080, y + 200), x + 1260, y + 200)
    is_roll = _compare_int(group, "EQUAL", kind, _int_value(group, CMD_ROLL, x + 1080, y + 160), x + 1260, y + 160)
    is_push = _compare_int(group, "EQUAL", kind, _int_value(group, CMD_PUSH, x + 1080, y + 80), x + 1260, y + 80)
    is_pop = _compare_int(group, "EQUAL", kind, _int_value(group, CMD_POP, x + 1080, y + 40), x + 1260, y + 40)

    heading = _rotate_vector_native(group, (1.0, 0.0, 0.0), rotation, x + 1440, y + 420)
    scaled_heading = _vector_math(group, "SCALE", [heading, value], TYPE_VECTOR, x + 1620, y + 420)
    moved_position = _vector_math(group, "ADD", [position, scaled_heading], TYPE_VECTOR, x + 1800, y + 420)
    radians = _value(group, 3.141592653589793 / 180.0, x + 1440, y + 80)
    angle_rad = _vectorless_multiply(group, value, radians, x + 1620, y + 80)
    signed_rad = _vectorless_multiply(group, angle_rad, sign, x + 1800, y + 80)

    yaw_delta = _axis_angle_rotation(group, (0.0, 0.0, 1.0), signed_rad, x + 1980, y + 260)
    pitch_delta = _axis_angle_rotation(group, (0.0, 1.0, 0.0), signed_rad, x + 1980, y + 180)
    roll_delta = _axis_angle_rotation(group, (1.0, 0.0, 0.0), signed_rad, x + 1980, y + 100)
    yaw_rotation = _compose_rotation(group, rotation, yaw_delta, x + 2160, y + 260)
    pitch_rotation = _compose_rotation(group, rotation, pitch_delta, x + 2160, y + 180)
    roll_rotation = _compose_rotation(group, rotation, roll_delta, x + 2160, y + 100)
    rotated = _switch_rotation(group, is_yaw, rotation, yaw_rotation, x + 2340, y + 260)
    rotated = _switch_rotation(group, is_pitch, rotated, pitch_rotation, x + 2520, y + 220)
    rotated = _switch_rotation(group, is_roll, rotated, roll_rotation, x + 2700, y + 180)
    moved_or_same = _switch(group, is_move, position, moved_position, x + 2160, y + 420)

    pushed_point = _single_point(group, position, x + 2160, y - 180)
    pushed_point = _store_named_attribute_geometry(group, pushed_point, STACK_ROTATION_ATTR, rotation, domain="POINT", data_type="QUATERNION", x=x + 2340, y=y - 180)
    pushed_point = _store_named_attribute_geometry(group, pushed_point, STACK_PATH_ID_ATTR, path_id, domain="POINT", data_type="INT", x=x + 2520, y=y - 180)
    pushed_point = _store_named_attribute_geometry(group, pushed_point, STACK_DEPTH_ATTR, branch_depth, domain="POINT", data_type="INT", x=x + 2700, y=y - 180)
    joined_stack = _join_geometry_values(group, [stack, pushed_point], x + 2880, y - 180)
    stack_after_push = _switch(group, is_push, stack, joined_stack, x + 3060, y - 180)

    wanted_depth = _int_math(group, "SUBTRACT", branch_depth, _int_value(group, 1, x + 2160, y - 300), x + 2340, y - 300)
    stack_depth_field = _named_attribute(group, STACK_DEPTH_ATTR, "INT", TYPE_INT, x + 2520, y - 300)
    wanted_selection = _compare_int(group, "EQUAL", stack_depth_field, wanted_depth, x + 2700, y - 300)
    selected_frame, stack_without_frame = _separate_points(group, stack_after_push, wanted_selection, x + 2880, y - 300)
    selected_count = _domain_point_count(group, selected_frame, x + 3060, y - 300)
    has_frame = _compare_int(group, "GREATER_THAN", selected_count, _int_value(group, 0, x + 3060, y - 360), x + 3240, y - 300)
    valid_pop = _boolean_math(group, "AND", [is_pop, has_frame], x + 3420, y - 300)

    saved_position_field = _new_node(group, "GeometryNodeInputPosition", x + 2880, y - 420)
    zero_index = _int_value(group, 0, x + 3060, y - 420)
    saved_position = _sample_index_typed(group, selected_frame, Value(saved_position_field.outputs[0], TYPE_VECTOR), zero_index, "FLOAT_VECTOR", TYPE_VECTOR, x + 3240, y - 420)
    saved_rotation = _sample_stack_rotation(group, selected_frame, x + 3060, y - 520)
    saved_path = _sample_attr(group, selected_frame, STACK_PATH_ID_ATTR, "INT", TYPE_INT, _int_value(group, 0, x + 3060, y - 620), x + 3240, y - 620)

    next_position = _switch(group, valid_pop, moved_or_same, saved_position, x + 3600, y + 420)
    next_rotation = _switch_rotation(group, valid_pop, rotated, saved_rotation, x + 3600, y + 260)
    depth_inc = _int_math(group, "ADD", branch_depth, _int_value(group, 1, x + 3300, y - 80), x + 3480, y - 80)
    after_push_depth = _switch(group, is_push, branch_depth, depth_inc, x + 3660, y - 80)
    next_depth = _switch(group, valid_pop, after_push_depth, wanted_depth, x + 3840, y - 80)
    after_push_path = _switch(group, is_push, path_id, next_path_id, x + 3480, y - 140)
    next_path = _switch(group, valid_pop, after_push_path, saved_path, x + 3660, y - 140)
    incremented_next_path = _int_math(group, "ADD", next_path_id, _int_value(group, 1, x + 3300, y - 220), x + 3480, y - 220)
    final_next_path = _switch(group, is_push, next_path_id, incremented_next_path, x + 3660, y - 220)
    next_stack = _switch(group, valid_pop, stack_after_push, stack_without_frame, x + 3840, y - 300)

    state_geo = _store_current_row(group, state_geo, iteration, SEGMENT_START_ATTR, position, "FLOAT_VECTOR", x + 2340, y + 520)
    state_geo = _set_current_row_position(group, state_geo, iteration, next_position, x + 2580, y + 520)
    state_geo = _store_current_row(group, state_geo, iteration, ROTATION_ATTR, next_rotation, "QUATERNION", x + 2820, y + 520)
    state_geo = _store_current_row(group, state_geo, iteration, MARKER_DEPTH_ATTR, next_depth, "INT", x + 3060, y + 520)
    state_geo = _store_current_row(group, state_geo, iteration, MARKER_PATH_ID_ATTR, next_path, "INT", x + 3300, y + 520)

    outputs = {
        "State Geometry": state_geo, "Branch Stack Geometry": next_stack,
        "Position": next_position, "Rotation": next_rotation,
        "Branch Depth": next_depth, "Path ID": next_path, "Next Path ID": final_next_path,
    }
    for name, result in outputs.items():
        group.links.new(result.socket, _input_socket(ro, name))
    return _repeat_output(ro, "State Geometry", TYPE_GEOMETRY)


def _vectorless_multiply(group, left: Value, right: Value, x=0, y=0) -> Value:
    """Multiply two Float values with a Shader Math node."""
    if left.typ != TYPE_FLOAT or right.typ != TYPE_FLOAT:
        raise CompileError("L-system float multiply expects Float values")
    node = _new_node(group, "ShaderNodeMath", x, y)
    node.operation = "MULTIPLY"
    group.links.new(left.socket, node.inputs[0])
    group.links.new(right.socket, node.inputs[1])
    return Value(node.outputs[0], TYPE_FLOAT)


def _materialize_segments(group, state_geo: Value, module_def_geo: Value, x=0, y=0) -> Value:
    """Create one Curve Line for every evaluated draw-command row."""
    module_ref = _named_attribute(group, MODULE_REF_ATTR, "INT", TYPE_INT, x, y + 160)
    draw_mask = _sample_attr(group, module_def_geo, DRAW_MASK_ATTR, "BOOLEAN", TYPE_BOOL, module_ref, x + 180, y + 120)
    draw_points, _ = _separate_points(group, state_geo, draw_mask, x + 180, y + 120)
    fi = _new_node(group, "GeometryNodeForeachGeometryElementInput", x + 420, y + 120)
    fo = _new_node(group, "GeometryNodeForeachGeometryElementOutput", x + 1320, y + 120)
    if not fi.pair_with_output(fo):
        raise CompileError("Could not pair dynamic L-system segment For Each zone")
    for item in list(fo.generation_items):
        fo.generation_items.remove(item)
    fo.generation_items.new("GEOMETRY", "Segments")
    fo.domain = "POINT"
    group.links.new(draw_points.socket, _input_socket(fi, "Geometry"))
    index = Value(_output_socket(fi, "Index"), TYPE_INT)
    start = _sample_attr(group, draw_points, SEGMENT_START_ATTR, "FLOAT_VECTOR", TYPE_VECTOR, index, x + 620, y + 220)
    position_field = _new_node(group, "GeometryNodeInputPosition", x + 620, y + 120)
    end = _sample_index_typed(
        group, draw_points, Value(position_field.outputs[0], TYPE_VECTOR), index,
        "FLOAT_VECTOR", TYPE_VECTOR, x + 800, y + 120,
    )
    line = _new_node(group, "GeometryNodeCurvePrimitiveLine", x + 900, y + 140)
    line.mode = "POINTS"
    group.links.new(start.socket, _input_socket(line, "Start"))
    group.links.new(end.socket, _input_socket(line, "End"))
    group.links.new(_output_socket(line, "Curve"), _input_socket(fo, "Segments"))
    return Value(_output_socket(fo, "Segments"), TYPE_GEOMETRY)


def _materialize_markers(comp, state_geo: Value, module_def_geo: Value, encoding: RuntimeGrammarEncoding, x=0, y=0) -> Value:
    """Extract marker rows, then decode immutable marker payload from ``module_ref``."""
    module_ref = _named_attribute(comp.group, MODULE_REF_ATTR, "INT", TYPE_INT, x, y + 100)
    marker_mask = _sample_attr(comp.group, module_def_geo, MARKER_MASK_ATTR, "BOOLEAN", TYPE_BOOL, module_ref, x + 180, y + 100)
    markers, _ = _separate_points(comp.group, state_geo, marker_mask, x + 360, y)
    marker_ref = _named_attribute(comp.group, MODULE_REF_ATTR, "INT", TYPE_INT, x + 560, y + 100)
    rotation = _named_attribute(comp.group, ROTATION_ATTR, "QUATERNION", TYPE_ROTATION, x + 740, y + 180)
    tangent = _rotate_vector_native(comp.group, (1.0, 0.0, 0.0), rotation, x + 920, y + 200)
    up = _rotate_vector_native(comp.group, (0.0, 0.0, 1.0), rotation, x + 920, y + 140)
    markers = _store_named_attribute_geometry(comp.group, markers, MARKER_TANGENT_ATTR, tangent, domain="POINT", data_type="FLOAT_VECTOR", x=x + 1100, y=y + 200)
    markers = _store_named_attribute_geometry(comp.group, markers, MARKER_UP_ATTR, up, domain="POINT", data_type="FLOAT_VECTOR", x=x + 1280, y=y + 140)

    payload_specs = [
        (MARKER_ID_ATTRS[0], "INT", TYPE_INT), (MARKER_ID_ATTRS[1], "INT", TYPE_INT),
        (MARKER_ID_ATTRS[2], "INT", TYPE_INT), (MARKER_ID_ATTRS[3], "INT", TYPE_INT),
        (MARKER_MASK_ATTR, "BOOLEAN", TYPE_BOOL), (MARKER_ITERATION_ATTR, "INT", TYPE_INT),
    ]
    for name in encoding.marker_parameter_names:
        payload_specs.append((name, "FLOAT", TYPE_FLOAT))
        payload_specs.append((f"nf_lsys_marker_param_index_{name}", "INT", TYPE_INT))
    for offset, (name, data_type, typ) in enumerate(payload_specs):
        value = _sample_attr(comp.group, module_def_geo, name, data_type, typ, marker_ref, x + 940, y - offset * 55)
        markers = _store_named_attribute_geometry(
            comp.group, markers, name, value, domain="POINT", data_type=data_type, x=x + 1140 + offset * 160, y=y - offset * 55,
        )

    table = type("DynamicMarkerParamTable", (), {
        "runtime_params": encoding.runtime_params,
        "marker_param_static": {name: () for name in encoding.marker_parameter_names},
    })()
    return _store_runtime_marker_params(comp, markers, table, x=x + 1400 + len(payload_specs) * 160, y=y - 80)


def runtime_dynamic_backend(comp, spec: LSystemSpec, *, x=0, y=0) -> Value:
    """Compile runtime derivation and a stream-sized spatial turtle into Geometry Nodes."""
    if not isinstance(spec.iterations, Value) or spec.iterations.typ != TYPE_INT:
        raise CompileError("runtime_dynamic_backend requires runtime Int iterations")
    encoding = encode_runtime_grammar(spec)
    tx = getattr(comp, "generated_resource_transaction", None)
    if tx is None:
        tx = resources.create_transaction(comp.group)
        comp.generated_resource_transaction = tx
    hint = getattr(comp.group, "name", "NodeForge")
    _mesh, axiom_obj = resources.create_runtime_axiom_object(tx, encoding.axiom, name_hint=hint + ".Axiom")
    _mesh, successor_obj = resources.create_runtime_successor_object(tx, encoding.successors, name_hint=hint + ".Successors")
    _mesh, rule_obj = resources.create_runtime_rule_index_object(tx, encoding.rule_index, name_hint=hint + ".Rules")
    _mesh, module_obj = resources.create_runtime_module_definitions_object(tx, encoding.module_definitions, name_hint=hint + ".Modules")
    axiom_geo = _object_geometry_from_generated(comp, axiom_obj, x=x, y=y + 260)
    successor_geo = _object_geometry_from_generated(comp, successor_obj, x=x, y=y + 80)
    rule_geo = _object_geometry_from_generated(comp, rule_obj, x=x, y=y - 100)
    module_def_geo = _object_geometry_from_generated(comp, module_obj, x=x, y=y - 280)

    final_string = _runtime_rewrite(comp.group, axiom_geo, successor_geo, rule_geo, module_def_geo, spec.iterations, x + 280, y)
    state_geo = _dynamic_turtle(comp.group, final_string, module_def_geo, encoding, x + 4100, y)
    segments = _materialize_segments(comp.group, state_geo, module_def_geo, x + 9300, y + 180)
    markers = _materialize_markers(comp, state_geo, module_def_geo, encoding, x + 9300, y - 180)
    return _join_geometry_values(comp.group, [segments, markers], x + 11100, y)


__all__ = [
    "RuntimeGrammarEncoding",
    "RuntimeStringTable",
    "RuntimeModuleDefinitionsTable",
    "RuntimeRuleIndexTable",
    "encode_runtime_grammar",
    "runtime_dynamic_backend",
]
