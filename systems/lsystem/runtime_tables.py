"""Compile-time command tables for runtime L-systems."""

from __future__ import annotations

from dataclasses import dataclass, field
from math import cos, radians, sin

from NodeForge.errors import CompileError
from NodeForge.extension_api import ExtensionBackendValue
from .interface import _Module as LSystemModule


def _is_const_number(value) -> bool:
    """Return whether *value* is a detached numeric scalar, excluding Bool."""
    return type(value) in {int, float}

MOVE_MASK_ATTR = "nf_lsys_move_mask"
HEADING_INDEX_ATTR = "nf_lsys_heading_index"
DRAW_MASK_ATTR = "nf_lsys_draw_mask"
PATH_ID_ATTR = "nf_lsys_path_id"
PATH_DEPTH_ATTR = "nf_lsys_path_depth"
PARENT_ATTACH_INDEX_ATTR = "nf_lsys_parent_attach_index"
ANCHOR_MASK_ATTR = "nf_lsys_anchor_mask"
LOCAL_POSITION_ATTR = "nf_lsys_local_position"
WORLD_POSITION_ATTR = "nf_lsys_world_position"
MOVE_DISTANCE_STATIC_ATTR = "nf_lsys_move_distance_static"
MOVE_PARAM_INDEX_ATTR = "nf_lsys_move_param_index"
TURN_DEGREES_STATIC_ATTR = "nf_lsys_turn_degrees_static"
TURN_PARAM_INDEX_ATTR = "nf_lsys_turn_param_index"
TURN_SIGN_ATTR = "nf_lsys_turn_sign"
MARKER_ID_ATTRS = (
    "nf_lsys_marker_id_a",
    "nf_lsys_marker_id_b",
    "nf_lsys_marker_id_c",
    "nf_lsys_marker_id_d",
)
MARKER_MASK_ATTR = "nf_lsys_marker_mask"
MARKER_TANGENT_ATTR = "nf_lsys_marker_tangent"
MARKER_UP_ATTR = "nf_lsys_marker_up"
MARKER_DEPTH_ATTR = "nf_lsys_marker_depth"
MARKER_PATH_ID_ATTR = "nf_lsys_marker_path_id"
MARKER_ITERATION_ATTR = "nf_lsys_marker_iteration"


@dataclass(frozen=True)
class BranchFreeCommandTable:
    """Linear command table consumed by the vectorized runtime backend."""

    vertices: tuple[tuple[float, float, float], ...]
    edges: tuple[tuple[int, int], ...]
    move_mask: tuple[float, ...]
    heading_index: tuple[float, ...]
    draw_mask: tuple[bool, ...]
    symbol_count: int
    draw_count: int
    move_distance_static: tuple[float, ...] = ()
    move_param_index: tuple[int, ...] = ()
    turn_degrees_static: tuple[float, ...] = ()
    turn_param_index: tuple[int, ...] = ()
    turn_sign: tuple[float, ...] = ()
    marker_id: tuple[tuple[int, int, int, int], ...] = ()
    marker_tangent: tuple[tuple[float, float, float], ...] = ()
    marker_up: tuple[tuple[float, float, float], ...] = ()
    marker_mask: tuple[bool, ...] = ()
    marker_depth: tuple[int, ...] = ()
    marker_path_id: tuple[int, ...] = ()
    marker_iteration: tuple[int, ...] = ()
    runtime_params: tuple[tuple[str, ExtensionBackendValue], ...] = ()
    marker_param_static: dict[str, tuple[float, ...]] = field(default_factory=dict)
    marker_param_index: dict[str, tuple[int, ...]] = field(default_factory=dict)
    marker_count: int = 0

    @property
    def vertex_count(self) -> int:
        return len(self.vertices)

    @property
    def edge_count(self) -> int:
        return len(self.edges)


@dataclass(frozen=True)
class BranchPathRecord:
    """One logical linear turtle path in a branched runtime command table."""

    path_id: int
    parent_path_id: int
    parent_attach_point_index: int
    anchor_point_index: int
    depth: int
    initial_heading_index: int


@dataclass(frozen=True)
class BranchAwareCommandTable:
    """Path-decomposed command table consumed by the branched runtime backend."""

    vertices: tuple[tuple[float, float, float], ...]
    edges: tuple[tuple[int, int], ...]
    move_mask: tuple[float, ...]
    heading_index: tuple[float, ...]
    draw_mask: tuple[bool, ...]
    anchor_mask: tuple[bool, ...]
    path_id: tuple[int, ...]
    path_depth: tuple[int, ...]
    parent_attach_index: tuple[int, ...]
    paths: tuple[BranchPathRecord, ...]
    symbol_count: int
    draw_count: int
    max_branch_depth: int
    move_distance_static: tuple[float, ...] = ()
    move_param_index: tuple[int, ...] = ()
    turn_degrees_static: tuple[float, ...] = ()
    turn_param_index: tuple[int, ...] = ()
    turn_sign: tuple[float, ...] = ()
    marker_id: tuple[tuple[int, int, int, int], ...] = ()
    marker_tangent: tuple[tuple[float, float, float], ...] = ()
    marker_up: tuple[tuple[float, float, float], ...] = ()
    marker_mask: tuple[bool, ...] = ()
    marker_depth: tuple[int, ...] = ()
    marker_path_id: tuple[int, ...] = ()
    marker_iteration: tuple[int, ...] = ()
    runtime_params: tuple[tuple[str, ExtensionBackendValue], ...] = ()
    marker_param_static: dict[str, tuple[float, ...]] = field(default_factory=dict)
    marker_param_index: dict[str, tuple[int, ...]] = field(default_factory=dict)
    marker_count: int = 0

    @property
    def vertex_count(self) -> int:
        return len(self.vertices)

    @property
    def edge_count(self) -> int:
        return len(self.edges)


@dataclass
class _PathState:
    path_id: int
    parent_path_id: int
    parent_attach_point_index: int
    anchor_point_index: int
    depth: int
    initial_heading_index: int
    current_point_index: int
    heading: int
    heading_static: float = 0.0
    heading_coeffs: dict[int, float] = field(default_factory=dict)


def _legacy_modules(stream: str) -> tuple[LSystemModule, ...]:
    return tuple(LSystemModule(ch, (), ch) for ch in stream)


def _runtime_slot(runtime_slots: list[tuple[str, ExtensionBackendValue]], name: str, value) -> int:
    if not isinstance(value, ExtensionBackendValue):
        return -1
    for idx, (slot_name, slot_value) in enumerate(runtime_slots):
        if slot_name == name and slot_value is value:
            return idx
    runtime_slots.append((name, value))
    return len(runtime_slots) - 1


def _number_or_slot(value, source: str, runtime_slots: list[tuple[str, ExtensionBackendValue]]) -> tuple[float, int]:
    if isinstance(value, ExtensionBackendValue):
        return 0.0, _runtime_slot(runtime_slots, source, value)
    if _is_const_number(value):
        return float(value), -1
    raise CompileError("L-system runtime table received non-numeric module argument")


def _effective_move(module: LSystemModule, step, runtime_slots: list[tuple[str, ExtensionBackendValue]]) -> tuple[float, int]:
    if module.args:
        arg = module.args[0]
        return _number_or_slot(arg.value, arg.param_name or arg.source, runtime_slots)
    return _number_or_slot(step, "__ls_step__", runtime_slots)


def _effective_turn(module: LSystemModule, angle_degrees, sign: float, runtime_slots: list[tuple[str, ExtensionBackendValue]]) -> tuple[float, int, float]:
    if module.args:
        arg = module.args[0]
        static, idx = _number_or_slot(arg.value, arg.param_name or arg.source, runtime_slots)
    else:
        static, idx = _number_or_slot(angle_degrees, "__ls_angle__", runtime_slots)
    if idx >= 0:
        return 0.0, idx, sign
    return sign * static, -1, 0.0


def _init_marker_arrays():
    return {
        "ids": [], "tangent": [], "up": [], "mask": [], "depth": [], "path": [], "iteration": [],
        "param_static": {}, "param_index": {},
    }


def _tangent_from_degrees(degrees: float) -> tuple[float, float, float]:
    angle = radians(float(degrees))
    return (cos(angle), sin(angle), 0.0)


def _append_marker_attrs(arrays, *, marker=None, module=None, depth=0, path_id=0, tangent=(0.0, 0.0, 0.0), up=(0.0, 0.0, 1.0), runtime_slots=None):
    is_marker = marker is not None
    arrays["ids"].append(marker.marker_identity if is_marker else (0, 0, 0, 0))
    arrays["tangent"].append(tuple(float(v) for v in tangent) if is_marker else (0.0, 0.0, 0.0))
    arrays["up"].append(tuple(float(v) for v in up) if is_marker else (0.0, 0.0, 0.0))
    arrays["mask"].append(bool(is_marker))
    arrays["depth"].append(depth if is_marker else 0)
    arrays["path"].append(path_id if is_marker else 0)
    arrays["iteration"].append(0 if is_marker else -1)
    for attr_name in list(arrays["param_static"]):
        arrays["param_static"][attr_name].append(0.0)
        arrays["param_index"][attr_name].append(-1)
    if not is_marker:
        return
    for attr_name, arg in zip(marker.parameter_names, module.args):
        if attr_name not in arrays["param_static"]:
            arrays["param_static"][attr_name] = [0.0] * len(arrays["mask"])
            arrays["param_index"][attr_name] = [-1] * len(arrays["mask"])
        static, idx = _number_or_slot(arg.value, arg.param_name or arg.source, runtime_slots)
        arrays["param_static"][attr_name][-1] = static
        arrays["param_index"][attr_name][-1] = idx


def build_branch_free_command_table(stream, *, angle_degrees=90.0, step=1.0, markers=None) -> BranchFreeCommandTable:
    """Build a generated-mesh command table for a branch-free expanded stream."""
    modules = _legacy_modules(stream) if isinstance(stream, str) else tuple(stream)
    if any(module.name in {"[", "]"} for module in modules):
        raise CompileError("branch_free_vectorized_runtime_backend received a branched L-system stream")
    markers = markers or {}
    vertices: list[tuple[float, float, float]] = []
    edges: list[tuple[int, int]] = []
    move_mask: list[float] = []
    heading_index: list[float] = []
    draw_mask: list[bool] = []
    move_distance_static: list[float] = []
    move_param_index: list[int] = []
    turn_degrees_static: list[float] = []
    turn_param_index: list[int] = []
    turn_sign: list[float] = []
    runtime_slots: list[tuple[str, ExtensionBackendValue]] = []
    marker_arrays = _init_marker_arrays()
    heading = 0
    heading_static_degrees = 0.0
    draw_count = 0
    marker_count = 0

    def add_point(*, move_old=0.0, heading_old=0, marker_tangent=(0.0, 0.0, 0.0), move_static=0.0, move_idx=-1, turn_static=0.0, turn_idx=-1, turn_s=0.0, marker=None, module=None):
        vertices.append((0.0, 0.0, 0.0))
        move_mask.append(float(move_old))
        heading_index.append(float(heading_old))
        move_distance_static.append(float(move_static))
        move_param_index.append(int(move_idx))
        turn_degrees_static.append(float(turn_static))
        turn_param_index.append(int(turn_idx))
        turn_sign.append(float(turn_s))
        _append_marker_attrs(marker_arrays, marker=marker, module=module, depth=0, path_id=0, tangent=marker_tangent, runtime_slots=runtime_slots)

    for module in modules:
        name = module.name
        if name in markers:
            add_point(heading_old=heading, marker_tangent=_tangent_from_degrees(heading_static_degrees), marker=markers[name], module=module)
            marker_count += 1
            continue
        start_i = len(vertices)
        add_point(heading_old=heading)
        start_heading = heading
        end_heading = heading
        old_move = 0.0
        edge_draw = False
        mv_static = 0.0
        mv_idx = -1
        t_static = 0.0
        t_idx = -1
        t_sign = 0.0
        if name == "+":
            t_static, t_idx, t_sign = _effective_turn(module, angle_degrees, 1.0, runtime_slots)
            end_heading = heading + 1
            heading = end_heading
            heading_static_degrees += t_static
        elif name == "-":
            t_static, t_idx, t_sign = _effective_turn(module, angle_degrees, -1.0, runtime_slots)
            end_heading = heading - 1
            heading = end_heading
            heading_static_degrees += t_static
        elif name in {"F", "f"}:
            mv_static, mv_idx = _effective_move(module, step, runtime_slots)
            old_move = 1.0
            edge_draw = name == "F"
            if edge_draw:
                draw_count += 1
        add_point(move_old=old_move, heading_old=end_heading, move_static=mv_static, move_idx=mv_idx, turn_static=t_static, turn_idx=t_idx, turn_s=t_sign)
        edges.append((start_i, start_i + 1))
        draw_mask.append(edge_draw)

    if draw_count <= 0 and marker_count <= 0:
        raise CompileError("Branch-free runtime L-system backend requires at least one drawn F segment")

    return BranchFreeCommandTable(
        vertices=tuple(vertices), edges=tuple(edges), move_mask=tuple(move_mask), heading_index=tuple(heading_index),
        draw_mask=tuple(draw_mask), symbol_count=len(modules), draw_count=draw_count,
        move_distance_static=tuple(move_distance_static), move_param_index=tuple(move_param_index),
        turn_degrees_static=tuple(turn_degrees_static), turn_param_index=tuple(turn_param_index), turn_sign=tuple(turn_sign),
        marker_id=tuple(marker_arrays["ids"]), marker_tangent=tuple(marker_arrays["tangent"]), marker_up=tuple(marker_arrays["up"]), marker_mask=tuple(marker_arrays["mask"]), marker_depth=tuple(marker_arrays["depth"]),
        marker_path_id=tuple(marker_arrays["path"]), marker_iteration=tuple(marker_arrays["iteration"]),
        runtime_params=tuple(runtime_slots), marker_param_static={k: tuple(v) for k, v in marker_arrays["param_static"].items()},
        marker_param_index={k: tuple(v) for k, v in marker_arrays["param_index"].items()}, marker_count=marker_count,
    )


def build_branch_aware_command_table(stream, *, angle_degrees=90.0, step=1.0, markers=None) -> BranchAwareCommandTable:
    """Build a generated-mesh command table for branched runtime L-systems."""
    modules = _legacy_modules(stream) if isinstance(stream, str) else tuple(stream)
    markers = markers or {}
    vertices: list[tuple[float, float, float]] = []
    edges: list[tuple[int, int]] = []
    move_mask: list[float] = []
    heading_index: list[float] = []
    draw_mask: list[bool] = []
    anchor_mask: list[bool] = []
    path_id_values: list[int] = []
    path_depth_values: list[int] = []
    parent_attach_values: list[int] = []
    move_distance_static: list[float] = []
    move_param_index: list[int] = []
    turn_degrees_static: list[float] = []
    turn_param_index: list[int] = []
    turn_sign: list[float] = []
    runtime_slots: list[tuple[str, ExtensionBackendValue]] = []
    marker_arrays = _init_marker_arrays()
    paths: list[BranchPathRecord] = []
    draw_count = 0
    marker_count = 0
    max_branch_depth = 0

    def add_point(state: _PathState, *, move: float, heading: int, anchor: bool, move_static=0.0, move_idx=-1, turn_static=0.0, turn_idx=-1, turn_s=0.0, marker=None, module=None) -> int:
        point_index = len(vertices)
        vertices.append((0.0, 0.0, 0.0))
        move_mask.append(float(move)); heading_index.append(float(heading)); anchor_mask.append(bool(anchor))
        path_id_values.append(state.path_id); path_depth_values.append(state.depth); parent_attach_values.append(state.parent_attach_point_index)
        move_distance_static.append(float(move_static)); move_param_index.append(int(move_idx)); turn_degrees_static.append(float(turn_static)); turn_param_index.append(int(turn_idx)); turn_sign.append(float(turn_s))
        _append_marker_attrs(marker_arrays, marker=marker, module=module, depth=state.depth, path_id=state.path_id, tangent=_tangent_from_degrees(state.heading_static), runtime_slots=runtime_slots)
        return point_index

    def new_path(parent_path_id: int, parent_attach_point_index: int, depth: int, initial_heading: int, *, heading_static=0.0, heading_coeffs=None) -> _PathState:
        path_id = len(paths)
        heading_coeffs = dict(heading_coeffs or {})
        dummy = _PathState(path_id, parent_path_id, parent_attach_point_index, -1, depth, initial_heading, -1, initial_heading, heading_static, dict(heading_coeffs))
        anchor_index = add_point(dummy, move=0.0, heading=initial_heading, anchor=True, turn_static=heading_static)
        state = _PathState(path_id, parent_path_id, parent_attach_point_index, anchor_index, depth, initial_heading, anchor_index, initial_heading, heading_static, dict(heading_coeffs))
        paths.append(BranchPathRecord(path_id, parent_path_id, parent_attach_point_index, anchor_index, depth, initial_heading))
        for slot_idx, coeff in sorted(heading_coeffs.items()):
            if coeff:
                state.current_point_index = add_point(state, move=0.0, heading=initial_heading, anchor=False, turn_idx=slot_idx, turn_s=coeff)
        return state

    current = new_path(parent_path_id=-1, parent_attach_point_index=-1, depth=0, initial_heading=0)
    stack: list[_PathState] = []
    for module in modules:
        name = module.name
        if name == "[":
            stack.append(current)
            child = new_path(
                current.path_id,
                current.current_point_index,
                current.depth + 1,
                current.heading,
                heading_static=current.heading_static,
                heading_coeffs=current.heading_coeffs,
            )
            max_branch_depth = max(max_branch_depth, child.depth)
            current = child
            continue
        if name == "]":
            if not stack:
                raise CompileError("L-system branch-aware runtime table received unmatched ]")
            current = stack.pop()
            continue
        if name in markers:
            add_point(current, move=0.0, heading=current.heading, anchor=False, marker=markers[name], module=module)
            marker_count += 1
            continue
        start_index = current.current_point_index
        end_heading = current.heading
        old_move = 0.0
        edge_draw = False
        mv_static = 0.0; mv_idx = -1; t_static = 0.0; t_idx = -1; t_sign = 0.0
        if name == "+":
            t_static, t_idx, t_sign = _effective_turn(module, angle_degrees, 1.0, runtime_slots)
            end_heading = current.heading + 1
            if t_idx >= 0:
                current.heading_coeffs[t_idx] = current.heading_coeffs.get(t_idx, 0.0) + t_sign
            else:
                current.heading_static += t_static
        elif name == "-":
            t_static, t_idx, t_sign = _effective_turn(module, angle_degrees, -1.0, runtime_slots)
            end_heading = current.heading - 1
            if t_idx >= 0:
                current.heading_coeffs[t_idx] = current.heading_coeffs.get(t_idx, 0.0) + t_sign
            else:
                current.heading_static += t_static
        elif name in {"F", "f"}:
            mv_static, mv_idx = _effective_move(module, step, runtime_slots)
            old_move = 1.0; edge_draw = name == "F"
            if edge_draw: draw_count += 1
        end_index = add_point(current, move=old_move, heading=end_heading, anchor=False, move_static=mv_static, move_idx=mv_idx, turn_static=t_static, turn_idx=t_idx, turn_s=t_sign)
        edges.append((start_index, end_index)); draw_mask.append(edge_draw)
        current.current_point_index = end_index; current.heading = end_heading
    if stack:
        raise CompileError("L-system branch-aware runtime table received unclosed [")
    if draw_count <= 0 and marker_count <= 0:
        raise CompileError("Branch-aware runtime L-system backend requires at least one drawn F segment")
    return BranchAwareCommandTable(
        vertices=tuple(vertices), edges=tuple(edges), move_mask=tuple(move_mask), heading_index=tuple(heading_index), draw_mask=tuple(draw_mask),
        anchor_mask=tuple(anchor_mask), path_id=tuple(path_id_values), path_depth=tuple(path_depth_values), parent_attach_index=tuple(parent_attach_values),
        paths=tuple(paths), symbol_count=len(modules), draw_count=draw_count, max_branch_depth=max_branch_depth,
        move_distance_static=tuple(move_distance_static), move_param_index=tuple(move_param_index), turn_degrees_static=tuple(turn_degrees_static),
        turn_param_index=tuple(turn_param_index), turn_sign=tuple(turn_sign), marker_id=tuple(marker_arrays["ids"]), marker_tangent=tuple(marker_arrays["tangent"]), marker_up=tuple(marker_arrays["up"]), marker_mask=tuple(marker_arrays["mask"]),
        marker_depth=tuple(marker_arrays["depth"]), marker_path_id=tuple(marker_arrays["path"]), marker_iteration=tuple(marker_arrays["iteration"]),
        runtime_params=tuple(runtime_slots), marker_param_static={k: tuple(v) for k, v in marker_arrays["param_static"].items()},
        marker_param_index={k: tuple(v) for k, v in marker_arrays["param_index"].items()}, marker_count=marker_count,
    )


PARENT_STATE_INDEX_ATTR = "nf_lsys_parent_state_index"
COMMAND_KIND_ATTR = "nf_lsys_command_kind"
COMMAND_VALUE_STATIC_ATTR = "nf_lsys_value_static"
COMMAND_VALUE_PARAM_INDEX_ATTR = "nf_lsys_value_param_index"
COMMAND_SIGN_ATTR = "nf_lsys_command_sign"
HEADING_ATTR = "nf_lsys_heading"
LEFT_ATTR = "nf_lsys_left"
UP_ATTR = "nf_lsys_up"

CMD_INITIAL = 0
CMD_MOVE_DRAW = 1
CMD_MOVE_NO_DRAW = 2
CMD_YAW = 3
CMD_PITCH = 4
CMD_ROLL = 5
CMD_MARKER = 6
CMD_PUSH = 7
CMD_POP = 8


def encode_command_fields(module: LSystemModule, *, angle_degrees, step, markers, runtime_slots: list[tuple[str, ExtensionBackendValue]]):
    """Encode one module's generic turtle command fields for runtime backends.

    Returns ``(kind, value_static, value_param_index, sign)``. Unknown
    developmental symbols are encoded as no-op commands. Marker payload is
    handled separately because it also depends on marker declarations.
    """
    name = module.name
    if name in {"F", "f"}:
        static, idx = _effective_move(module, step, runtime_slots)
        return (CMD_MOVE_DRAW if name == "F" else CMD_MOVE_NO_DRAW, static, idx, 0.0)
    if name in {"+", "-", "^", "&", "/", "\\"}:
        if name in {"+", "-"}:
            kind, sign = CMD_YAW, (1.0 if name == "+" else -1.0)
        elif name in {"^", "&"}:
            kind, sign = CMD_PITCH, (-1.0 if name == "^" else 1.0)
        else:
            kind, sign = CMD_ROLL, (1.0 if name == "/" else -1.0)
        if module.args:
            arg = module.args[0]
            static, idx = _number_or_slot(arg.value, arg.param_name or arg.source, runtime_slots)
        else:
            static, idx = _number_or_slot(angle_degrees, "__ls_angle__", runtime_slots)
        return kind, static, idx, sign
    if name == "[":
        return CMD_PUSH, 0.0, -1, 0.0
    if name == "]":
        return CMD_POP, 0.0, -1, 0.0
    if name in markers:
        return CMD_MARKER, 0.0, -1, 0.0
    return CMD_INITIAL, 0.0, -1, 0.0


def encode_marker_payload(module: LSystemModule, *, markers, runtime_slots: list[tuple[str, ExtensionBackendValue]], parameter_names: tuple[str, ...]):
    """Encode marker identity and declared parameter slots for one module."""
    marker = markers.get(module.name)
    static = {name: 0.0 for name in parameter_names}
    indexes = {name: -1 for name in parameter_names}
    if marker is None:
        return (0, 0, 0, 0), False, -1, static, indexes
    for attr_name, arg in zip(marker.parameter_names, module.args):
        value, idx = _number_or_slot(arg.value, arg.param_name or arg.source, runtime_slots)
        static[attr_name] = value
        indexes[attr_name] = idx
    return marker.marker_identity, True, 0, static, indexes


@dataclass(frozen=True)
class SpatialCommandTable:
    """Sequential state table for runtime spatial turtle evaluation."""

    vertices: tuple[tuple[float, float, float], ...]
    edges: tuple[tuple[int, int], ...]
    parent_state_index: tuple[int, ...]
    command_kind: tuple[int, ...]
    value_static: tuple[float, ...]
    value_param_index: tuple[int, ...]
    command_sign: tuple[float, ...]
    draw_mask: tuple[bool, ...]
    marker_id: tuple[tuple[int, int, int, int], ...]
    marker_tangent: tuple[tuple[float, float, float], ...]
    marker_up: tuple[tuple[float, float, float], ...]
    marker_mask: tuple[bool, ...]
    marker_depth: tuple[int, ...]
    marker_path_id: tuple[int, ...]
    marker_iteration: tuple[int, ...]
    runtime_params: tuple[tuple[str, ExtensionBackendValue], ...]
    marker_param_static: dict[str, tuple[float, ...]]
    marker_param_index: dict[str, tuple[int, ...]]
    symbol_count: int
    draw_count: int
    marker_count: int

    @property
    def vertex_count(self) -> int:
        """Return the number of sequential turtle state rows."""
        return len(self.vertices)

    @property
    def edge_count(self) -> int:
        """Return the number of prebuilt drawn edges."""
        return len(self.edges)


def build_spatial_command_table(stream, *, angle_degrees=90.0, step=1.0, markers=None) -> SpatialCommandTable:
    """Build the compile-time dependency table used by the spatial runtime backend."""
    modules = _legacy_modules(stream) if isinstance(stream, str) else tuple(stream)
    markers = markers or {}
    vertices = [(0.0, 0.0, 0.0)]
    edges = []
    parent = [0]
    kinds = [CMD_INITIAL]
    value_static = [0.0]
    value_param_index = [-1]
    signs = [0.0]
    draw_mask = []
    runtime_slots: list[tuple[str, ExtensionBackendValue]] = []
    marker_arrays = _init_marker_arrays()
    _append_marker_attrs(marker_arrays, runtime_slots=runtime_slots)
    state_index = 0
    branch_stack: list[tuple[int, int, int]] = []
    depth = 0
    path_id = 0
    next_path_id = 1
    draw_count = 0
    marker_count = 0

    def add_state(kind, *, static=0.0, param_idx=-1, sign=0.0, marker=None, module=None):
        nonlocal state_index, marker_count
        new_index = len(vertices)
        if state_index >= new_index:
            raise CompileError("L-system spatial command table requires parent_state_index < current_state_index")
        vertices.append((0.0, 0.0, 0.0))
        parent.append(state_index)
        kinds.append(int(kind))
        value_static.append(float(static))
        value_param_index.append(int(param_idx))
        signs.append(float(sign))
        _append_marker_attrs(
            marker_arrays, marker=marker, module=module, depth=depth, path_id=path_id,
            tangent=(0.0, 0.0, 0.0), up=(0.0, 0.0, 0.0), runtime_slots=runtime_slots,
        )
        state_index = new_index
        if marker is not None:
            marker_count += 1
        return new_index

    for module in modules:
        name = module.name
        if name == "[":
            branch_stack.append((state_index, depth, path_id))
            depth += 1
            path_id = next_path_id
            next_path_id += 1
            continue
        if name == "]":
            if not branch_stack:
                raise CompileError("L-system contains unmatched ]")
            state_index, depth, path_id = branch_stack.pop()
            continue
        if name in {"F", "f", "+", "-", "^", "&", "/", "\\"}:
            kind, static, idx, sign = encode_command_fields(
                module, angle_degrees=angle_degrees, step=step, markers=markers, runtime_slots=runtime_slots
            )
            if name in {"F", "f"}:
                old = state_index
                current = add_state(kind, static=static, param_idx=idx, sign=sign)
                if name == "F":
                    edges.append((old, current))
                    draw_mask.append(True)
                    draw_count += 1
            else:
                add_state(kind, static=static, param_idx=idx, sign=sign)
            continue
        if name in markers:
            add_state(CMD_MARKER, marker=markers[name], module=module)
            continue
        # Rewrite-only modules are deliberately ignored by the turtle interpreter.

    if branch_stack:
        raise CompileError("L-system contains unclosed [")
    if len(draw_mask) != len(edges):
        raise CompileError("Internal L-system spatial draw table mismatch")
    for idx, parent_idx in enumerate(parent[1:], start=1):
        if parent_idx >= idx:
            raise CompileError("L-system spatial command table parent dependency is not strictly earlier")
    return SpatialCommandTable(
        vertices=tuple(vertices), edges=tuple(edges), parent_state_index=tuple(parent), command_kind=tuple(kinds),
        value_static=tuple(value_static), value_param_index=tuple(value_param_index), command_sign=tuple(signs),
        draw_mask=tuple(draw_mask), marker_id=tuple(marker_arrays["ids"]), marker_tangent=tuple(marker_arrays["tangent"]),
        marker_up=tuple(marker_arrays["up"]), marker_mask=tuple(marker_arrays["mask"]), marker_depth=tuple(marker_arrays["depth"]),
        marker_path_id=tuple(marker_arrays["path"]), marker_iteration=tuple(marker_arrays["iteration"]),
        runtime_params=tuple(runtime_slots), marker_param_static={k: tuple(v) for k, v in marker_arrays["param_static"].items()},
        marker_param_index={k: tuple(v) for k, v in marker_arrays["param_index"].items()}, symbol_count=len(modules),
        draw_count=draw_count, marker_count=marker_count,
    )


__all__ = [
    "ANCHOR_MASK_ATTR", "BranchAwareCommandTable", "BranchFreeCommandTable", "BranchPathRecord", "SpatialCommandTable", "DRAW_MASK_ATTR",
    "HEADING_INDEX_ATTR", "LOCAL_POSITION_ATTR", "MOVE_MASK_ATTR", "PARENT_ATTACH_INDEX_ATTR", "PATH_DEPTH_ATTR", "PATH_ID_ATTR", "WORLD_POSITION_ATTR",
    "MOVE_DISTANCE_STATIC_ATTR", "MOVE_PARAM_INDEX_ATTR", "TURN_DEGREES_STATIC_ATTR", "TURN_PARAM_INDEX_ATTR", "TURN_SIGN_ATTR", "MARKER_ID_ATTRS", "MARKER_MASK_ATTR",
    "MARKER_TANGENT_ATTR", "MARKER_UP_ATTR", "MARKER_DEPTH_ATTR", "MARKER_PATH_ID_ATTR", "MARKER_ITERATION_ATTR",
    "PARENT_STATE_INDEX_ATTR", "COMMAND_KIND_ATTR", "COMMAND_VALUE_STATIC_ATTR", "COMMAND_VALUE_PARAM_INDEX_ATTR", "COMMAND_SIGN_ATTR",
    "HEADING_ATTR", "LEFT_ATTR", "UP_ATTR", "CMD_INITIAL", "CMD_MOVE_DRAW", "CMD_MOVE_NO_DRAW", "CMD_YAW", "CMD_PITCH", "CMD_ROLL", "CMD_MARKER", "CMD_PUSH", "CMD_POP",
    "encode_command_fields", "encode_marker_payload", "build_branch_aware_command_table", "build_branch_free_command_table", "build_spatial_command_table",
]
