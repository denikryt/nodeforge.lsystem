"""Runtime L-system rewriting and stream-sized spatial turtle backend.

This module owns the topology-dynamic path used when ``ls_iterations`` receives
an Int ``ExtensionBackendValue``. Grammar resources remain compile-time sized, while the active
L-string and branch stack are variable-size Geometry Nodes data.
"""

from __future__ import annotations

from dataclasses import dataclass

from NodeForge.errors import CompileError
from NodeForge.extension_api import ExtensionBackendValue, NFType

from . import resources
from .backends import (
    _boolean_math,
    _combine_xyz_mixed,
    _int_value,
    _new_node,
    _switch,
    _value,
    _vector_math,
    _input_socket,
    _join_geometry_values,
    _named_attribute,
    _object_geometry_from_generated,
    _output_socket,
    _resolve_numeric_arg,
    _sample_index_typed,
    _store_named_attribute_geometry,
    _store_runtime_marker_params,
)
from .interface import _LSystemSpec as LSystemSpec, _Module as LSystemModule
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
    runtime_params: tuple[tuple[str, ExtensionBackendValue], ...]
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
    runtime_slots: list[tuple[str, ExtensionBackendValue]] = []

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


def _int_math(context, operation: str, left: ExtensionBackendValue, right: ExtensionBackendValue, x=0, y=0) -> ExtensionBackendValue:
    """Create integer-safe Geometry Nodes arithmetic without float coercion."""
    if left.typ != NFType.INT or right.typ != NFType.INT:
        raise CompileError("L-system integer math expects Int values")
    node = _new_node(context, "FunctionNodeIntegerMath", x, y)
    node.operation = operation
    context.group.links.new(left.socket, node.inputs[0])
    context.group.links.new(right.socket, node.inputs[1])
    return context.value(node.outputs[0], NFType.INT)


def _compare_int(context, operation: str, left: ExtensionBackendValue, right: ExtensionBackendValue, x=0, y=0) -> ExtensionBackendValue:
    """Create an Int Compare node through the Blender 5.2 A/B -> Result contract."""
    if left.typ != NFType.INT or right.typ != NFType.INT:
        raise CompileError("L-system integer comparison expects Int values")
    node = _new_node(context, "FunctionNodeCompare", x, y)
    node.data_type = "INT"
    node.operation = operation
    context.group.links.new(left.socket, _input_socket(node, "A"))
    context.group.links.new(right.socket, _input_socket(node, "B"))
    return context.value(_output_socket(node, "Result"), NFType.BOOL)


def _switch_rotation(context, condition: ExtensionBackendValue, false_value: ExtensionBackendValue, true_value: ExtensionBackendValue, x=0, y=0) -> ExtensionBackendValue:
    """Select between native Blender Rotation values."""
    if condition.typ != NFType.BOOL or false_value.typ != NFType.ROTATION or true_value.typ != NFType.ROTATION:
        raise CompileError("L-system rotation switch expects Bool and Rotation values")
    node = _new_node(context, "GeometryNodeSwitch", x, y)
    node.input_type = "ROTATION"
    context.group.links.new(condition.socket, _input_socket(node, "Switch"))
    context.group.links.new(false_value.socket, _input_socket(node, "False"))
    context.group.links.new(true_value.socket, _input_socket(node, "True"))
    return context.value(_output_socket(node, "Output"), NFType.ROTATION)


def _identity_rotation(context, x=0, y=0) -> ExtensionBackendValue:
    """Create the identity native Blender Rotation."""
    node = _new_node(context, "FunctionNodeEulerToRotation", x, y)
    return context.value(_output_socket(node, "Rotation"), NFType.ROTATION)


def _axis_angle_rotation(context, axis, angle: ExtensionBackendValue, x=0, y=0) -> ExtensionBackendValue:
    """Create a native Rotation from a local canonical axis and runtime angle."""
    node = _new_node(context, "FunctionNodeAxisAngleToRotation", x, y)
    if isinstance(axis, ExtensionBackendValue):
        context.group.links.new(axis.socket, _input_socket(node, "Axis"))
    else:
        _input_socket(node, "Axis").default_value = tuple(axis)
    context.group.links.new(angle.socket, _input_socket(node, "Angle"))
    return context.value(_output_socket(node, "Rotation"), NFType.ROTATION)


def _compose_rotation(context, rotation: ExtensionBackendValue, rotate_by: ExtensionBackendValue, x=0, y=0) -> ExtensionBackendValue:
    """Compose the turtle orientation with one local-axis delta rotation."""
    node = _new_node(context, "FunctionNodeRotateRotation", x, y)
    context.group.links.new(rotate_by.socket, _input_socket(node, "Rotation"))
    context.group.links.new(rotation.socket, _input_socket(node, "Rotate By"))
    return context.value(_output_socket(node, "Rotation"), NFType.ROTATION)


def _rotate_vector_native(context, vector, rotation: ExtensionBackendValue, x=0, y=0) -> ExtensionBackendValue:
    """Rotate a vector by a native Blender Rotation."""
    node = _new_node(context, "FunctionNodeRotateVector", x, y)
    if isinstance(vector, ExtensionBackendValue):
        context.group.links.new(vector.socket, _input_socket(node, "Vector"))
    else:
        _input_socket(node, "Vector").default_value = tuple(vector)
    context.group.links.new(rotation.socket, _input_socket(node, "Rotation"))
    return context.value(_output_socket(node, "Vector"), NFType.VECTOR)


def _sample_attr(context, geometry: ExtensionBackendValue, name: str, data_type: str, typ: NFType, index: ExtensionBackendValue, x=0, y=0) -> ExtensionBackendValue:
    """Sample one named point attribute at an explicit integer index."""
    field = _named_attribute(context, name, data_type, typ, x, y)
    return _sample_index_typed(context, geometry, field, index, data_type, typ, x + 180, y)


def _domain_point_count(context, geometry: ExtensionBackendValue, x=0, y=0) -> ExtensionBackendValue:
    """Return the runtime point count of mesh geometry as an Int field."""
    node = _new_node(context, "GeometryNodeAttributeDomainSize", x, y)
    node.component = "MESH"
    context.group.links.new(geometry.socket, _input_socket(node, "Geometry"))
    return context.value(_output_socket(node, "Point Count"), NFType.INT)


def _duplicate_points(context, geometry: ExtensionBackendValue, amount: ExtensionBackendValue, x=0, y=0):
    """Duplicate point-domain modules by per-point successor cardinality."""
    node = _new_node(context, "GeometryNodeDuplicateElements", x, y)
    node.domain = "POINT"
    context.group.links.new(geometry.socket, _input_socket(node, "Geometry"))
    context.group.links.new(amount.socket, _input_socket(node, "Amount"))
    return context.value(_output_socket(node, "Geometry"), NFType.GEOMETRY), context.value(_output_socket(node, "Duplicate Index"), NFType.INT)


def _separate_points(context, geometry: ExtensionBackendValue, selection: ExtensionBackendValue, x=0, y=0) -> tuple[ExtensionBackendValue, ExtensionBackendValue]:
    """Split point geometry into selected and inverted outputs."""
    node = _new_node(context, "GeometryNodeSeparateGeometry", x, y)
    node.domain = "POINT"
    context.group.links.new(geometry.socket, _input_socket(node, "Geometry"))
    context.group.links.new(selection.socket, _input_socket(node, "Selection"))
    return context.value(_output_socket(node, "Selection"), NFType.GEOMETRY), context.value(_output_socket(node, "Inverted"), NFType.GEOMETRY)


def _empty_geometry_from(context, geometry: ExtensionBackendValue, x=0, y=0) -> ExtensionBackendValue:
    """Create empty point geometry by deleting all points from a seed geometry."""
    node = _new_node(context, "GeometryNodeDeleteGeometry", x, y)
    node.domain = "POINT"
    _input_socket(node, "Selection").default_value = True
    context.group.links.new(geometry.socket, _input_socket(node, "Geometry"))
    return context.value(_output_socket(node, "Geometry"), NFType.GEOMETRY)


def _single_point(context, position: ExtensionBackendValue, x=0, y=0) -> ExtensionBackendValue:
    """Create one mesh point at the supplied runtime position."""
    node = _new_node(context, "GeometryNodeMeshLine", x, y)
    node.mode = "OFFSET"
    _input_socket(node, "Count").default_value = 1
    context.group.links.new(position.socket, _input_socket(node, "Start Location"))
    return context.value(_output_socket(node, "Mesh"), NFType.GEOMETRY)


def _capture_rewrite_metadata(
    context, geometry: ExtensionBackendValue, has_rule: ExtensionBackendValue, successor_start: ExtensionBackendValue, x=0, y=0
) -> tuple[ExtensionBackendValue, ExtensionBackendValue, ExtensionBackendValue]:
    """Capture predecessor rule metadata as anonymous point attributes.

    The captured fields are evaluated on generation-N geometry before any
    successor payload is written, then propagated through Duplicate Elements.
    This preserves parallel L-system rewrite semantics without temporary named
    attributes or cleanup nodes.
    """
    node = _new_node(context, "GeometryNodeCaptureAttribute", x, y)
    node.domain = "POINT"
    node.capture_items.new("BOOLEAN", "Has Rule")
    node.capture_items.new("INT", "Successor Start")
    context.group.links.new(geometry.socket, _input_socket(node, "Geometry"))
    context.group.links.new(has_rule.socket, _input_socket(node, "Has Rule"))
    context.group.links.new(successor_start.socket, _input_socket(node, "Successor Start"))
    return (
        context.value(_output_socket(node, "Geometry"), NFType.GEOMETRY),
        context.value(_output_socket(node, "Has Rule"), NFType.BOOL),
        context.value(_output_socket(node, "Successor Start"), NFType.INT),
    )


def _rewrite_once(context, current: ExtensionBackendValue, successor_geo: ExtensionBackendValue, rule_index_geo: ExtensionBackendValue, module_def_geo: ExtensionBackendValue, x=0, y=0) -> ExtensionBackendValue:
    """Build one parallel derivation while copying only a single ``module_ref``."""
    predecessor_ref = _named_attribute(context, MODULE_REF_ATTR, "INT", NFType.INT, x, y)
    predecessor_symbol = _sample_attr(context, module_def_geo, SYMBOL_ID_ATTR, "INT", NFType.INT, predecessor_ref, x + 180, y)
    has_rule = _sample_attr(context, rule_index_geo, RULE_HAS_RULE_ATTR, "BOOLEAN", NFType.BOOL, predecessor_symbol, x + 360, y + 100)
    successor_start = _sample_attr(context, rule_index_geo, RULE_SUCCESSOR_START_ATTR, "INT", NFType.INT, predecessor_symbol, x + 360, y)
    successor_count = _sample_attr(context, rule_index_geo, RULE_SUCCESSOR_COUNT_ATTR, "INT", NFType.INT, predecessor_symbol, x + 360, y - 100)

    captured, rewrite_has_rule, rewrite_start = _capture_rewrite_metadata(
        context, current, has_rule, successor_start, x + 600, y + 60
    )
    amount = _switch(context, has_rule, _int_value(context, 1, x + 600, y - 180), successor_count, x + 800, y - 160)
    duplicated, duplicate_index = _duplicate_points(context, captured, amount, x + 1000, y)

    successor_row = _int_math(context, "ADD", rewrite_start, duplicate_index, x + 1200, y + 40)
    successor_ref = _sample_attr(context, successor_geo, MODULE_REF_ATTR, "INT", NFType.INT, successor_row, x + 1380, y)
    return _store_named_attribute_geometry(
        context, duplicated, MODULE_REF_ATTR, successor_ref, selection=rewrite_has_rule, domain="POINT", data_type="INT", x=x + 1560, y=y,
    )


def _runtime_rewrite(context, axiom_geo: ExtensionBackendValue, successor_geo: ExtensionBackendValue, rule_index_geo: ExtensionBackendValue, module_def_geo: ExtensionBackendValue, iterations: ExtensionBackendValue, x=0, y=0) -> ExtensionBackendValue:
    """Repeat the parallel rewrite step for a runtime non-negative count."""
    is_negative = _compare_int(context, "LESS_THAN", iterations, _int_value(context, 0, x, y + 140), x + 180, y + 140)
    safe_iterations = _switch(context, is_negative, iterations, _int_value(context, 0, x + 180, y + 80), x + 360, y + 120)

    ri = _new_node(context, "GeometryNodeRepeatInput", x + 520, y)
    ro = _new_node(context, "GeometryNodeRepeatOutput", x + 3600, y)
    if not ri.pair_with_output(ro):
        raise CompileError("Could not pair runtime L-system derivation Repeat Zone nodes")
    context.group.links.new(safe_iterations.socket, _input_socket(ri, "Iterations"))
    context.group.links.new(axiom_geo.socket, _input_socket(ri, "Geometry"))
    current = context.value(_output_socket(ri, "Geometry"), NFType.GEOMETRY)
    next_geo = _rewrite_once(context, current, successor_geo, rule_index_geo, module_def_geo, x + 760, y)
    context.group.links.new(next_geo.socket, _input_socket(ro, "Geometry"))
    return context.value(_output_socket(ro, "Geometry"), NFType.GEOMETRY)


def _add_repeat_item(ro, socket_type: str, name: str):
    """Add one explicit state item through the Blender 5.2 Repeat API."""
    ro.repeat_items.new(socket_type, name)


def _repeat_state(context, ri, name: str, typ: NFType) -> ExtensionBackendValue:
    """Wrap a Repeat Input state output through the extension backend boundary."""
    return context.value(_output_socket(ri, name), typ)


def _repeat_output(context, ro, name: str, typ: NFType) -> ExtensionBackendValue:
    """Wrap a Repeat Output state socket through the extension backend boundary."""
    return context.value(_output_socket(ro, name), typ)


def _store_current_row(context, geometry: ExtensionBackendValue, iteration: ExtensionBackendValue, name: str, value: ExtensionBackendValue, data_type: str, x=0, y=0) -> ExtensionBackendValue:
    """Write one evaluated state field only onto the current module row."""
    index_node = _new_node(context, "GeometryNodeInputIndex", x, y + 100)
    point_index = context.value(index_node.outputs[0], NFType.INT)
    selection = _compare_int(context, "EQUAL", point_index, iteration, x + 160, y + 100)
    return _store_named_attribute_geometry(context, geometry, name, value, selection=selection, domain="POINT", data_type=data_type, x=x + 340, y=y)


def _set_current_row_position(context, geometry: ExtensionBackendValue, iteration: ExtensionBackendValue, position: ExtensionBackendValue, x=0, y=0) -> ExtensionBackendValue:
    """Write the evaluated turtle position into the current runtime-string point."""
    index_node = _new_node(context, "GeometryNodeInputIndex", x, y + 100)
    point_index = context.value(index_node.outputs[0], NFType.INT)
    selection = _compare_int(context, "EQUAL", point_index, iteration, x + 160, y + 100)
    node = _new_node(context, "GeometryNodeSetPosition", x + 340, y)
    context.group.links.new(geometry.socket, _input_socket(node, "Geometry"))
    context.group.links.new(selection.socket, _input_socket(node, "Selection"))
    context.group.links.new(position.socket, _input_socket(node, "Position"))
    return context.value(_output_socket(node, "Geometry"), NFType.GEOMETRY)


def _sample_stack_rotation(context, stack: ExtensionBackendValue, x=0, y=0) -> ExtensionBackendValue:
    """Sample the native Rotation from the unique selected branch-stack frame."""
    return _sample_attr(context, stack, STACK_ROTATION_ATTR, "QUATERNION", NFType.ROTATION, _int_value(context, 0, x, y - 40), x + 100, y)


def _dynamic_turtle(context, final_string: ExtensionBackendValue, module_def_geo: ExtensionBackendValue, encoding: RuntimeGrammarEncoding, x=0, y=0) -> ExtensionBackendValue:
    """Interpret a variable-length L-string using native Blender Rotation state."""
    count = _domain_point_count(context, final_string, x, y + 360)
    initial_stack = _empty_geometry_from(context, final_string, x, y + 240)
    initial_position = _combine_xyz_mixed(context, [0.0, 0.0, 0.0], x, y + 160)
    initial_rotation = _identity_rotation(context, x, y + 80)

    ri = _new_node(context, "GeometryNodeRepeatInput", x + 280, y)
    ro = _new_node(context, "GeometryNodeRepeatOutput", x + 3900, y)
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

    context.group.links.new(count.socket, _input_socket(ri, "Iterations"))
    initial_values = {
        "State Geometry": final_string, "Branch Stack Geometry": initial_stack,
        "Position": initial_position, "Rotation": initial_rotation,
        "Branch Depth": _int_value(context, 0, x + 100, y - 180),
        "Path ID": _int_value(context, 0, x + 100, y - 240),
        "Next Path ID": _int_value(context, 1, x + 100, y - 300),
    }
    for name, value in initial_values.items():
        context.group.links.new(value.socket, _input_socket(ri, name))

    state_geo = _repeat_state(context, ri, "State Geometry", NFType.GEOMETRY)
    stack = _repeat_state(context, ri, "Branch Stack Geometry", NFType.GEOMETRY)
    position = _repeat_state(context, ri, "Position", NFType.VECTOR)
    rotation = _repeat_state(context, ri, "Rotation", NFType.ROTATION)
    branch_depth = _repeat_state(context, ri, "Branch Depth", NFType.INT)
    path_id = _repeat_state(context, ri, "Path ID", NFType.INT)
    next_path_id = _repeat_state(context, ri, "Next Path ID", NFType.INT)
    iteration = context.value(_output_socket(ri, "Iteration"), NFType.INT)

    module_ref = _sample_attr(context, final_string, MODULE_REF_ATTR, "INT", NFType.INT, iteration, x + 620, y + 320)
    kind = _sample_attr(context, module_def_geo, COMMAND_KIND_ATTR, "INT", NFType.INT, module_ref, x + 800, y + 260)
    static = _sample_attr(context, module_def_geo, COMMAND_VALUE_STATIC_ATTR, "FLOAT", NFType.FLOAT, module_ref, x + 800, y + 180)
    param_index = _sample_attr(context, module_def_geo, COMMAND_VALUE_PARAM_INDEX_ATTR, "INT", NFType.INT, module_ref, x + 800, y + 100)
    sign = _sample_attr(context, module_def_geo, COMMAND_SIGN_ATTR, "FLOAT", NFType.FLOAT, module_ref, x + 800, y + 20)
    value = _resolve_numeric_arg(context, static, param_index, encoding.runtime_params, "Dynamic L-system command", x + 1040, y + 160)

    is_move_draw = _compare_int(context, "EQUAL", kind, _int_value(context, CMD_MOVE_DRAW, x + 1080, y + 340), x + 1260, y + 340)
    is_move_nodraw = _compare_int(context, "EQUAL", kind, _int_value(context, CMD_MOVE_NO_DRAW, x + 1080, y + 300), x + 1260, y + 300)
    is_move = _boolean_math(context, "OR", [is_move_draw, is_move_nodraw], x + 1440, y + 320)
    is_yaw = _compare_int(context, "EQUAL", kind, _int_value(context, CMD_YAW, x + 1080, y + 240), x + 1260, y + 240)
    is_pitch = _compare_int(context, "EQUAL", kind, _int_value(context, CMD_PITCH, x + 1080, y + 200), x + 1260, y + 200)
    is_roll = _compare_int(context, "EQUAL", kind, _int_value(context, CMD_ROLL, x + 1080, y + 160), x + 1260, y + 160)
    is_push = _compare_int(context, "EQUAL", kind, _int_value(context, CMD_PUSH, x + 1080, y + 80), x + 1260, y + 80)
    is_pop = _compare_int(context, "EQUAL", kind, _int_value(context, CMD_POP, x + 1080, y + 40), x + 1260, y + 40)

    heading = _rotate_vector_native(context, (1.0, 0.0, 0.0), rotation, x + 1440, y + 420)
    scaled_heading = _vector_math(context, "SCALE", [heading, value], NFType.VECTOR, x + 1620, y + 420)
    moved_position = _vector_math(context, "ADD", [position, scaled_heading], NFType.VECTOR, x + 1800, y + 420)
    radians = _value(context, 3.141592653589793 / 180.0, x + 1440, y + 80)
    angle_rad = _vectorless_multiply(context, value, radians, x + 1620, y + 80)
    signed_rad = _vectorless_multiply(context, angle_rad, sign, x + 1800, y + 80)

    yaw_delta = _axis_angle_rotation(context, (0.0, 0.0, 1.0), signed_rad, x + 1980, y + 260)
    pitch_delta = _axis_angle_rotation(context, (0.0, 1.0, 0.0), signed_rad, x + 1980, y + 180)
    roll_delta = _axis_angle_rotation(context, (1.0, 0.0, 0.0), signed_rad, x + 1980, y + 100)
    yaw_rotation = _compose_rotation(context, rotation, yaw_delta, x + 2160, y + 260)
    pitch_rotation = _compose_rotation(context, rotation, pitch_delta, x + 2160, y + 180)
    roll_rotation = _compose_rotation(context, rotation, roll_delta, x + 2160, y + 100)
    rotated = _switch_rotation(context, is_yaw, rotation, yaw_rotation, x + 2340, y + 260)
    rotated = _switch_rotation(context, is_pitch, rotated, pitch_rotation, x + 2520, y + 220)
    rotated = _switch_rotation(context, is_roll, rotated, roll_rotation, x + 2700, y + 180)
    moved_or_same = _switch(context, is_move, position, moved_position, x + 2160, y + 420)

    pushed_point = _single_point(context, position, x + 2160, y - 180)
    pushed_point = _store_named_attribute_geometry(context, pushed_point, STACK_ROTATION_ATTR, rotation, domain="POINT", data_type="QUATERNION", x=x + 2340, y=y - 180)
    pushed_point = _store_named_attribute_geometry(context, pushed_point, STACK_PATH_ID_ATTR, path_id, domain="POINT", data_type="INT", x=x + 2520, y=y - 180)
    pushed_point = _store_named_attribute_geometry(context, pushed_point, STACK_DEPTH_ATTR, branch_depth, domain="POINT", data_type="INT", x=x + 2700, y=y - 180)
    joined_stack = _join_geometry_values(context, [stack, pushed_point], x + 2880, y - 180)
    stack_after_push = _switch(context, is_push, stack, joined_stack, x + 3060, y - 180)

    wanted_depth = _int_math(context, "SUBTRACT", branch_depth, _int_value(context, 1, x + 2160, y - 300), x + 2340, y - 300)
    stack_depth_field = _named_attribute(context, STACK_DEPTH_ATTR, "INT", NFType.INT, x + 2520, y - 300)
    wanted_selection = _compare_int(context, "EQUAL", stack_depth_field, wanted_depth, x + 2700, y - 300)
    selected_frame, stack_without_frame = _separate_points(context, stack_after_push, wanted_selection, x + 2880, y - 300)
    selected_count = _domain_point_count(context, selected_frame, x + 3060, y - 300)
    has_frame = _compare_int(context, "GREATER_THAN", selected_count, _int_value(context, 0, x + 3060, y - 360), x + 3240, y - 300)
    valid_pop = _boolean_math(context, "AND", [is_pop, has_frame], x + 3420, y - 300)

    saved_position_field = _new_node(context, "GeometryNodeInputPosition", x + 2880, y - 420)
    zero_index = _int_value(context, 0, x + 3060, y - 420)
    saved_position = _sample_index_typed(context, selected_frame, context.value(saved_position_field.outputs[0], NFType.VECTOR), zero_index, "FLOAT_VECTOR", NFType.VECTOR, x + 3240, y - 420)
    saved_rotation = _sample_stack_rotation(context, selected_frame, x + 3060, y - 520)
    saved_path = _sample_attr(context, selected_frame, STACK_PATH_ID_ATTR, "INT", NFType.INT, _int_value(context, 0, x + 3060, y - 620), x + 3240, y - 620)

    next_position = _switch(context, valid_pop, moved_or_same, saved_position, x + 3600, y + 420)
    next_rotation = _switch_rotation(context, valid_pop, rotated, saved_rotation, x + 3600, y + 260)
    depth_inc = _int_math(context, "ADD", branch_depth, _int_value(context, 1, x + 3300, y - 80), x + 3480, y - 80)
    after_push_depth = _switch(context, is_push, branch_depth, depth_inc, x + 3660, y - 80)
    next_depth = _switch(context, valid_pop, after_push_depth, wanted_depth, x + 3840, y - 80)
    after_push_path = _switch(context, is_push, path_id, next_path_id, x + 3480, y - 140)
    next_path = _switch(context, valid_pop, after_push_path, saved_path, x + 3660, y - 140)
    incremented_next_path = _int_math(context, "ADD", next_path_id, _int_value(context, 1, x + 3300, y - 220), x + 3480, y - 220)
    final_next_path = _switch(context, is_push, next_path_id, incremented_next_path, x + 3660, y - 220)
    next_stack = _switch(context, valid_pop, stack_after_push, stack_without_frame, x + 3840, y - 300)

    state_geo = _store_current_row(context, state_geo, iteration, SEGMENT_START_ATTR, position, "FLOAT_VECTOR", x + 2340, y + 520)
    state_geo = _set_current_row_position(context, state_geo, iteration, next_position, x + 2580, y + 520)
    state_geo = _store_current_row(context, state_geo, iteration, ROTATION_ATTR, next_rotation, "QUATERNION", x + 2820, y + 520)
    state_geo = _store_current_row(context, state_geo, iteration, MARKER_DEPTH_ATTR, next_depth, "INT", x + 3060, y + 520)
    state_geo = _store_current_row(context, state_geo, iteration, MARKER_PATH_ID_ATTR, next_path, "INT", x + 3300, y + 520)

    outputs = {
        "State Geometry": state_geo, "Branch Stack Geometry": next_stack,
        "Position": next_position, "Rotation": next_rotation,
        "Branch Depth": next_depth, "Path ID": next_path, "Next Path ID": final_next_path,
    }
    for name, result in outputs.items():
        context.group.links.new(result.socket, _input_socket(ro, name))
    return _repeat_output(context, ro, "State Geometry", NFType.GEOMETRY)


def _vectorless_multiply(context, left: ExtensionBackendValue, right: ExtensionBackendValue, x=0, y=0) -> ExtensionBackendValue:
    """Multiply two Float values with a Shader Math node."""
    if left.typ != NFType.FLOAT or right.typ != NFType.FLOAT:
        raise CompileError("L-system float multiply expects Float values")
    node = _new_node(context, "ShaderNodeMath", x, y)
    node.operation = "MULTIPLY"
    context.group.links.new(left.socket, node.inputs[0])
    context.group.links.new(right.socket, node.inputs[1])
    return context.value(node.outputs[0], NFType.FLOAT)


def _materialize_segments(context, state_geo: ExtensionBackendValue, module_def_geo: ExtensionBackendValue, x=0, y=0) -> ExtensionBackendValue:
    """Create one Curve Line for every evaluated draw-command row."""
    module_ref = _named_attribute(context, MODULE_REF_ATTR, "INT", NFType.INT, x, y + 160)
    draw_mask = _sample_attr(context, module_def_geo, DRAW_MASK_ATTR, "BOOLEAN", NFType.BOOL, module_ref, x + 180, y + 120)
    draw_points, _ = _separate_points(context, state_geo, draw_mask, x + 180, y + 120)
    fi = _new_node(context, "GeometryNodeForeachGeometryElementInput", x + 420, y + 120)
    fo = _new_node(context, "GeometryNodeForeachGeometryElementOutput", x + 1320, y + 120)
    if not fi.pair_with_output(fo):
        raise CompileError("Could not pair dynamic L-system segment For Each zone")
    for item in list(fo.generation_items):
        fo.generation_items.remove(item)
    fo.generation_items.new("GEOMETRY", "Segments")
    fo.domain = "POINT"
    context.group.links.new(draw_points.socket, _input_socket(fi, "Geometry"))
    index = context.value(_output_socket(fi, "Index"), NFType.INT)
    start = _sample_attr(context, draw_points, SEGMENT_START_ATTR, "FLOAT_VECTOR", NFType.VECTOR, index, x + 620, y + 220)
    position_field = _new_node(context, "GeometryNodeInputPosition", x + 620, y + 120)
    end = _sample_index_typed(
        context, draw_points, context.value(position_field.outputs[0], NFType.VECTOR), index,
        "FLOAT_VECTOR", NFType.VECTOR, x + 800, y + 120,
    )
    line = _new_node(context, "GeometryNodeCurvePrimitiveLine", x + 900, y + 140)
    line.mode = "POINTS"
    context.group.links.new(start.socket, _input_socket(line, "Start"))
    context.group.links.new(end.socket, _input_socket(line, "End"))
    context.group.links.new(_output_socket(line, "Curve"), _input_socket(fo, "Segments"))
    return context.value(_output_socket(fo, "Segments"), NFType.GEOMETRY)


def _materialize_markers(context, state_geo: ExtensionBackendValue, module_def_geo: ExtensionBackendValue, encoding: RuntimeGrammarEncoding, x=0, y=0) -> ExtensionBackendValue:
    """Extract marker rows, then decode immutable marker payload from ``module_ref``."""
    module_ref = _named_attribute(context, MODULE_REF_ATTR, "INT", NFType.INT, x, y + 100)
    marker_mask = _sample_attr(context, module_def_geo, MARKER_MASK_ATTR, "BOOLEAN", NFType.BOOL, module_ref, x + 180, y + 100)
    markers, _ = _separate_points(context, state_geo, marker_mask, x + 360, y)
    marker_ref = _named_attribute(context, MODULE_REF_ATTR, "INT", NFType.INT, x + 560, y + 100)
    rotation = _named_attribute(context, ROTATION_ATTR, "QUATERNION", NFType.ROTATION, x + 740, y + 180)
    tangent = _rotate_vector_native(context, (1.0, 0.0, 0.0), rotation, x + 920, y + 200)
    up = _rotate_vector_native(context, (0.0, 0.0, 1.0), rotation, x + 920, y + 140)
    markers = _store_named_attribute_geometry(context, markers, MARKER_TANGENT_ATTR, tangent, domain="POINT", data_type="FLOAT_VECTOR", x=x + 1100, y=y + 200)
    markers = _store_named_attribute_geometry(context, markers, MARKER_UP_ATTR, up, domain="POINT", data_type="FLOAT_VECTOR", x=x + 1280, y=y + 140)

    payload_specs = [
        (MARKER_ID_ATTRS[0], "INT", NFType.INT), (MARKER_ID_ATTRS[1], "INT", NFType.INT),
        (MARKER_ID_ATTRS[2], "INT", NFType.INT), (MARKER_ID_ATTRS[3], "INT", NFType.INT),
        (MARKER_MASK_ATTR, "BOOLEAN", NFType.BOOL), (MARKER_ITERATION_ATTR, "INT", NFType.INT),
    ]
    for name in encoding.marker_parameter_names:
        payload_specs.append((name, "FLOAT", NFType.FLOAT))
        payload_specs.append((f"nf_lsys_marker_param_index_{name}", "INT", NFType.INT))
    for offset, (name, data_type, typ) in enumerate(payload_specs):
        value = _sample_attr(context, module_def_geo, name, data_type, typ, marker_ref, x + 940, y - offset * 55)
        markers = _store_named_attribute_geometry(
            context, markers, name, value, domain="POINT", data_type=data_type, x=x + 1140 + offset * 160, y=y - offset * 55,
        )

    return _store_runtime_marker_params(
        context,
        markers,
        marker_parameter_names=encoding.marker_parameter_names,
        runtime_params=encoding.runtime_params,
        x=x + 1400 + len(payload_specs) * 160,
        y=y - 80,
    )


def runtime_dynamic_backend(context, spec: LSystemSpec, *, x=0, y=0) -> ExtensionBackendValue:
    """Compile runtime derivation and a stream-sized spatial turtle into Geometry Nodes."""
    if not isinstance(spec.iterations, ExtensionBackendValue) or spec.iterations.typ != NFType.INT:
        raise CompileError("runtime_dynamic_backend requires runtime Int iterations")
    encoding = encode_runtime_grammar(spec)
    hint = getattr(context.group, "name", "NodeForge")
    _mesh, axiom_obj = resources.create_runtime_axiom_object(context, encoding.axiom, name_hint=hint + ".Axiom")
    _mesh, successor_obj = resources.create_runtime_successor_object(context, encoding.successors, name_hint=hint + ".Successors")
    _mesh, rule_obj = resources.create_runtime_rule_index_object(context, encoding.rule_index, name_hint=hint + ".Rules")
    _mesh, module_obj = resources.create_runtime_module_definitions_object(context, encoding.module_definitions, name_hint=hint + ".Modules")
    axiom_geo = _object_geometry_from_generated(context, axiom_obj, x=x, y=y + 260)
    successor_geo = _object_geometry_from_generated(context, successor_obj, x=x, y=y + 80)
    rule_geo = _object_geometry_from_generated(context, rule_obj, x=x, y=y - 100)
    module_def_geo = _object_geometry_from_generated(context, module_obj, x=x, y=y - 280)

    final_string = _runtime_rewrite(context, axiom_geo, successor_geo, rule_geo, module_def_geo, spec.iterations, x + 280, y)
    state_geo = _dynamic_turtle(context, final_string, module_def_geo, encoding, x + 4100, y)
    segments = _materialize_segments(context, state_geo, module_def_geo, x + 9300, y + 180)
    markers = _materialize_markers(context, state_geo, module_def_geo, encoding, x + 9300, y - 180)
    return _join_geometry_values(context, [segments, markers], x + 11100, y)


__all__ = [
    "RuntimeGrammarEncoding",
    "RuntimeStringTable",
    "RuntimeModuleDefinitionsTable",
    "RuntimeRuleIndexTable",
    "encode_runtime_grammar",
    "runtime_dynamic_backend",
]
