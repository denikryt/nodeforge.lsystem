"""Spatial turtle interpretation for parsed L-system module streams."""

import math

from NodeForge.errors import CompileError
from NodeForge.geometry import _is_const_number
from NodeForge.nodes import _combine_xyz_mixed, _is_number_type, _math, _value, _vector_math
from NodeForge.constants import TYPE_FLOAT, TYPE_VECTOR
from NodeForge.values import Value
from .model import LSystemModule, TurtleFrame, TurtleInterpretation, TurtleMarkerPoint, TurtlePoint, TurtleSegment


def _as_numeric_value(group, value, x, y, label):
    """Return *value* as a numeric Value, creating constants when necessary."""
    if isinstance(value, Value):
        if not _is_number_type(value.typ):
            raise CompileError(f"{label} must be numeric")
        return value
    if _is_const_number(value):
        return _value(group, value, x, y)
    raise CompileError(f"{label} must be numeric")




def _add(group, a, b, x, y):
    """Add static numbers directly or emit a Math node for runtime values."""
    if _is_const_number(a) and _is_const_number(b):
        return float(a) + float(b)
    return _math(group, "ADD", [_as_numeric_value(group, a, x - 80, y, "add operand"), _as_numeric_value(group, b, x - 80, y - 40, "add operand")], x, y)


def _sub(group, a, b, x, y):
    """Subtract static numbers directly or emit a Math node for runtime values."""
    if _is_const_number(a) and _is_const_number(b):
        return float(a) - float(b)
    return _math(group, "SUBTRACT", [_as_numeric_value(group, a, x - 80, y, "subtract operand"), _as_numeric_value(group, b, x - 80, y - 40, "subtract operand")], x, y)


def _cos(group, value, x, y):
    """Compute cosine statically or emit a Math node for runtime headings."""
    if _is_const_number(value):
        return math.cos(float(value))
    return _math(group, "COSINE", [_as_numeric_value(group, value, x - 80, y, "cos angle")], x, y)


def _sin(group, value, x, y):
    """Compute sine statically or emit a Math node for runtime headings."""
    if _is_const_number(value):
        return math.sin(float(value))
    return _math(group, "SINE", [_as_numeric_value(group, value, x - 80, y, "sin angle")], x, y)

def _mul(group, a, b, x, y):
    """Multiply static numbers directly or emit a Math node."""
    if _is_const_number(a) and _is_const_number(b):
        return float(a) * float(b)
    return _math(group, "MULTIPLY", [_as_numeric_value(group, a, x - 80, y, "multiply operand"), _as_numeric_value(group, b, x - 80, y - 40, "multiply operand")], x, y)


def _point_to_vector(group, point: TurtlePoint, x, y):
    """Create a Vector Value for a turtle point."""
    return _combine_xyz_mixed(group, [point.x, point.y, point.z], x, y)


def _angle_radians(group, angle_degrees, x, y):
    """Convert a DSL angle in degrees to radians."""
    return _mul(group, angle_degrees, math.pi / 180.0, x, y)


def _legacy_modules(stream: str) -> tuple[LSystemModule, ...]:
    return tuple(LSystemModule(ch, (), ch) for ch in stream)


def _effective_arg(module: LSystemModule, default):
    return module.args[0].value if module.args else default


def _require_const(value, label):
    if not _is_const_number(value):
        raise CompileError(f"static L-system {label} must be a compile-time number")
    return float(value)


def _p_add(a: TurtlePoint, b: TurtlePoint) -> TurtlePoint:
    return TurtlePoint(a.x + b.x, a.y + b.y, a.z + b.z)


def _p_scale(v: TurtlePoint, s: float) -> TurtlePoint:
    return TurtlePoint(v.x * s, v.y * s, v.z * s)


def _p_dot(a: TurtlePoint, b: TurtlePoint) -> float:
    return a.x * b.x + a.y * b.y + a.z * b.z


def _p_cross(a: TurtlePoint, b: TurtlePoint) -> TurtlePoint:
    return TurtlePoint(a.y * b.z - a.z * b.y, a.z * b.x - a.x * b.z, a.x * b.y - a.y * b.x)


def _p_normalize(v: TurtlePoint) -> TurtlePoint:
    length = math.sqrt(_p_dot(v, v))
    if length <= 1e-12:
        raise CompileError("L-system turtle encountered a zero-length orientation axis")
    return _p_scale(v, 1.0 / length)


def rotate_about_axis_static(vector: TurtlePoint, axis: TurtlePoint, radians_value: float) -> TurtlePoint:
    """Rotate *vector* around *axis* with Rodrigues' axis-angle formula."""
    axis = _p_normalize(axis)
    c = math.cos(radians_value)
    s = math.sin(radians_value)
    return _p_add(
        _p_add(_p_scale(vector, c), _p_scale(_p_cross(axis, vector), s)),
        _p_scale(axis, _p_dot(axis, vector) * (1.0 - c)),
    )


def rotate_about_axis_runtime(group, vector: Value, axis: Value, radians_value: Value, x=0, y=0) -> Value:
    """Build a generic runtime Rodrigues rotation for Vector node values."""
    if vector.typ != TYPE_VECTOR or axis.typ != TYPE_VECTOR or radians_value.typ not in {TYPE_FLOAT, "INT"}:
        raise CompileError("L-system runtime rotation expects Vector, Vector, numeric")
    axis_n = _vector_math(group, "NORMALIZE", [axis], TYPE_VECTOR, x, y)
    c = _math(group, "COSINE", [radians_value], x + 180, y)
    s = _math(group, "SINE", [radians_value], x + 180, y - 80)
    one_minus_c = _math(group, "SUBTRACT", [_value(group, 1.0, x + 160, y - 160), c], x + 360, y - 160)
    term1 = _vector_math(group, "SCALE", [vector, c], TYPE_VECTOR, x + 360, y)
    cross = _vector_math(group, "CROSS_PRODUCT", [axis_n, vector], TYPE_VECTOR, x + 360, y - 80)
    term2 = _vector_math(group, "SCALE", [cross, s], TYPE_VECTOR, x + 540, y - 80)
    dot = _vector_math(group, "DOT_PRODUCT", [axis_n, vector], TYPE_FLOAT, x + 360, y - 240)
    proj_scale = _math(group, "MULTIPLY", [dot, one_minus_c], x + 540, y - 200)
    term3 = _vector_math(group, "SCALE", [axis_n, proj_scale], TYPE_VECTOR, x + 700, y - 200)
    sum12 = _vector_math(group, "ADD", [term1, term2], TYPE_VECTOR, x + 720, y)
    return _vector_math(group, "ADD", [sum12, term3], TYPE_VECTOR, x + 900, y)


def _rotated_frame_static(frame: TurtleFrame, command: str, radians_value: float) -> TurtleFrame:
    """Return a frame after one yaw, pitch, or roll command."""
    h, l, u = frame.heading, frame.left, frame.up
    if command in {"+", "-"}:
        a = radians_value if command == "+" else -radians_value
        h = _p_normalize(rotate_about_axis_static(h, u, a))
        l = _p_normalize(rotate_about_axis_static(l, u, a))
    elif command in {"^", "&"}:
        # Positive right-hand rotation around +Left points Heading downward, so ^ uses -angle.
        a = -radians_value if command == "^" else radians_value
        h = _p_normalize(rotate_about_axis_static(h, l, a))
        u = _p_normalize(rotate_about_axis_static(u, l, a))
    elif command in {"/", "\\"}:
        a = radians_value if command == "/" else -radians_value
        l = _p_normalize(rotate_about_axis_static(l, h, a))
        u = _p_normalize(rotate_about_axis_static(u, h, a))
    return TurtleFrame(frame.position, h, l, u)


def interpret(group, stream: str, *, angle_degrees, step, x=0, y=0) -> list[TurtleSegment]:
    """Interpret a legacy planar character stream, including runtime numeric values.

    The current compiler uses the newer module-stream backends. This helper keeps the
    historical internal behavior available for callers that still pass a raw 2D stream.
    """
    angle = _angle_radians(group, angle_degrees, x - 180, y - 80)
    pos = TurtlePoint(0.0, 0.0, 0.0)
    heading = 0.0
    stack = []
    segments = []
    op_index = 0
    for ch in stream:
        px = x + (op_index % 8) * 180
        py = y - (op_index // 8) * 280
        if ch == "+":
            heading = _add(group, heading, angle, px, py)
            op_index += 1
        elif ch == "-":
            heading = _sub(group, heading, angle, px, py)
            op_index += 1
        elif ch == "[":
            stack.append((pos, heading))
        elif ch == "]":
            if not stack:
                raise CompileError("L-system contains unmatched ]")
            pos, heading = stack.pop()
        elif ch in {"F", "f"}:
            dx = _mul(group, step, _cos(group, heading, px, py - 40), px, py - 80)
            dy = _mul(group, step, _sin(group, heading, px, py - 120), px, py - 160)
            next_pos = TurtlePoint(_add(group, pos.x, dx, px, py - 200), _add(group, pos.y, dy, px, py - 240), pos.z)
            if ch == "F":
                segments.append(TurtleSegment(pos, next_pos))
            pos = next_pos
            op_index += 1
    if stack:
        raise CompileError("L-system contains unclosed [")
    return segments


def interpret_static(stream, *, angle_degrees, step, markers=None, creation_iteration=None):
    """Interpret an expanded static stream with a full 3D Heading/Left/Up frame."""
    modules = _legacy_modules(stream) if isinstance(stream, str) else tuple(stream)
    markers = markers or {}
    default_angle = _require_const(angle_degrees, "angle")
    default_step = _require_const(step, "step")
    frame = TurtleFrame(
        position=TurtlePoint(0.0, 0.0, 0.0),
        heading=TurtlePoint(1.0, 0.0, 0.0),
        left=TurtlePoint(0.0, 1.0, 0.0),
        up=TurtlePoint(0.0, 0.0, 1.0),
    )
    stack = []
    next_path_id = 1
    path_id = 0
    branch_depth = 0
    segments = []
    marker_points = []
    for module in modules:
        name = module.name
        if name in {"+", "-", "^", "&", "/", "\\"}:
            degrees = _require_const(_effective_arg(module, default_angle), "angle")
            frame = _rotated_frame_static(frame, name, degrees * math.pi / 180.0)
        elif name == "[":
            stack.append((frame, branch_depth, path_id))
            branch_depth += 1
            path_id = next_path_id
            next_path_id += 1
        elif name == "]":
            if not stack:
                raise CompileError("L-system contains unmatched ]")
            frame, branch_depth, path_id = stack.pop()
        elif name in {"F", "f"}:
            distance = _require_const(_effective_arg(module, default_step), "step")
            next_pos = _p_add(frame.position, _p_scale(frame.heading, distance))
            if name == "F":
                segments.append(TurtleSegment(frame.position, next_pos))
            frame = TurtleFrame(next_pos, frame.heading, frame.left, frame.up)
        elif name in markers:
            marker = markers[name]
            params = {param_name: arg.value for param_name, arg in zip(marker.parameter_names, module.args)}
            marker_points.append(TurtleMarkerPoint(
                position=frame.position,
                heading=0.0,
                tangent=frame.heading,
                up=frame.up,
                branch_depth=branch_depth,
                path_id=path_id,
                creation_iteration=creation_iteration,
                marker_name=name,
                marker_identity=marker.marker_identity,
                parameters=params,
            ))
    if stack:
        raise CompileError("L-system contains unclosed [")
    return TurtleInterpretation(tuple(segments), tuple(marker_points))


__all__ = [
    "interpret", "interpret_static", "_point_to_vector", "_as_numeric_value",
    "rotate_about_axis_static", "rotate_about_axis_runtime",
]
