"""Structural analysis for expanded L-system command streams."""

from NodeForge.errors import CompileError
from NodeForge.extension_api import ExtensionBackendValue
from .interface import _Module as LSystemModule
from .model import LSystemAnalysis

_SPATIAL_ROTATIONS = {"^", "&", "/", "\\"}
_ALL_ROTATIONS = {"+", "-", "^", "&", "/", "\\"}


def _legacy_modules(stream: str) -> tuple[LSystemModule, ...]:
    return tuple(LSystemModule(ch, (), ch) for ch in stream)


def _arg_runtime(module: LSystemModule) -> bool:
    """Return whether the first module argument is a reconstructed runtime value."""
    return bool(module.args and isinstance(module.args[0].value, ExtensionBackendValue))


def analyze(stream, *, angle, step, markers=None) -> LSystemAnalysis:
    """Validate branch brackets and compute backend-selection metrics."""
    modules = _legacy_modules(stream) if isinstance(stream, str) else tuple(stream)
    marker_names = set(markers or ())
    depth = max_depth = segment_count = marker_count = 0
    has_branches = False
    has_spatial_rotation = False
    uses_runtime_angle = isinstance(angle, ExtensionBackendValue)
    uses_runtime_step = isinstance(step, ExtensionBackendValue)
    marker_param_runtime = False
    for module in modules:
        name = module.name
        if name == "F":
            segment_count += 1
        if name in {"F", "f"}:
            uses_runtime_step = uses_runtime_step or (_arg_runtime(module) if module.args else isinstance(step, ExtensionBackendValue))
        elif name in _ALL_ROTATIONS:
            has_spatial_rotation = has_spatial_rotation or name in _SPATIAL_ROTATIONS
            uses_runtime_angle = uses_runtime_angle or (_arg_runtime(module) if module.args else isinstance(angle, ExtensionBackendValue))
        elif name == "[":
            has_branches = True
            depth += 1
            max_depth = max(max_depth, depth)
        elif name == "]":
            has_branches = True
            depth -= 1
            if depth < 0:
                raise CompileError("L-system contains unmatched ]")
        elif name in marker_names:
            marker_count += 1
            marker_param_runtime = marker_param_runtime or any(isinstance(arg.value, ExtensionBackendValue) for arg in module.args)
    if depth != 0:
        raise CompileError("L-system contains unclosed [")
    return LSystemAnalysis(
        has_branches=has_branches,
        angle_is_runtime=uses_runtime_angle,
        step_is_runtime=uses_runtime_step,
        segment_count=segment_count,
        symbol_count=len(modules),
        max_branch_depth=max_depth,
        marker_count=marker_count,
        marker_param_is_runtime=marker_param_runtime,
        has_spatial_rotation=has_spatial_rotation,
    )


__all__ = ["analyze"]
