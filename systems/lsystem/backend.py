"""Physical Extension API v2 realization for the NodeForge L-System package."""

from __future__ import annotations

from NodeForge.errors import CompileError
from NodeForge.extension_api import ExtensionBackendValue

from .analysis import analyze
from .backends import (
    branch_aware_vectorized_runtime_backend,
    branch_free_vectorized_runtime_backend,
    filter_marker_points,
    select_backend_category,
    spatial_runtime_backend,
    static_baked_backend,
    validate_branch_aware_backend_available,
)
from .expander import expand
from .modules import validate_identifier
from .runtime_dynamic import runtime_dynamic_backend
from .runtime_tables import (
    build_branch_aware_command_table,
    build_branch_free_command_table,
    build_spatial_command_table,
)
from .turtle import interpret_static


def ls_points(context, geometry, *, marker):
    """Filter points emitted for one validated L-System marker identifier."""
    marker = validate_identifier(marker, "points() marker")
    x, y = context.location
    return filter_marker_points(context, geometry, marker, x=x, y=y)


def ls_system(context, spec):
    """Realize one reconstructed semantic L-System specification as Geometry Nodes."""
    x, y = context.location
    if isinstance(spec.iterations, ExtensionBackendValue):
        return runtime_dynamic_backend(context, spec, x=x, y=y)

    stream = expand(spec.axiom, spec.rules, spec.iterations)
    metrics = analyze(stream, angle=spec.angle, step=spec.step, markers=spec.markers)
    category = select_backend_category(metrics)
    if category == "static":
        interpretation = interpret_static(
            stream,
            angle_degrees=spec.angle,
            step=spec.step,
            markers=spec.markers,
            creation_iteration=spec.iterations,
        )
        return static_baked_backend(context, interpretation, x=x, y=y)
    if category == "spatial_runtime":
        table = build_spatial_command_table(
            stream,
            angle_degrees=spec.angle,
            step=spec.step,
            markers=spec.markers,
        )
        return spatial_runtime_backend(context, table, x=x, y=y)
    if category == "branch_free_runtime":
        table = build_branch_free_command_table(
            stream,
            angle_degrees=spec.angle,
            step=spec.step,
            markers=spec.markers,
        )
        return branch_free_vectorized_runtime_backend(
            context,
            table,
            angle_degrees=spec.angle,
            step=spec.step,
            x=x,
            y=y,
        )
    if category == "branched_runtime":
        validate_branch_aware_backend_available(metrics, category)
        table = build_branch_aware_command_table(
            stream,
            angle_degrees=spec.angle,
            step=spec.step,
            markers=spec.markers,
        )
        return branch_aware_vectorized_runtime_backend(
            context,
            table,
            angle_degrees=spec.angle,
            step=spec.step,
            x=x,
            y=y,
        )
    raise CompileError(f"Unsupported L-system backend category: {category}")
