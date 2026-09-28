"""Static spatial turtle interpretation for L-system module streams."""

import math

from NodeForge.errors import CompileError

from .interface import _Module as LSystemModule
from .model import (
    TurtleFrame,
    TurtleInterpretation,
    TurtleMarkerPoint,
    TurtlePoint,
    TurtleSegment,
)


def _is_const_number(value) -> bool:
    """Return whether *value* is a detached numeric scalar, excluding Bool."""
    return type(value) in {int, float}

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

__all__ = ["interpret_static", "rotate_about_axis_static"]
