"""Package-owned internal data records for L-System physical algorithms."""

from dataclasses import dataclass
from typing import Mapping

@dataclass(frozen=True)
class LSystemAnalysis:
    """Structural metrics for an expanded L-system command stream."""

    has_branches: bool
    angle_is_runtime: bool
    step_is_runtime: bool
    segment_count: int
    symbol_count: int
    max_branch_depth: int
    marker_count: int = 0
    marker_param_is_runtime: bool = False
    has_spatial_rotation: bool = False


@dataclass(frozen=True)
class TurtlePoint:
    """A world-space vector/point containing numeric components."""

    x: object
    y: object
    z: object


@dataclass(frozen=True)
class TurtleFrame:
    """Spatial turtle state using an orthonormal Heading/Left/Up basis."""

    position: TurtlePoint
    heading: TurtlePoint
    left: TurtlePoint
    up: TurtlePoint


@dataclass(frozen=True)
class TurtleSegment:
    """One drawn turtle segment."""

    start: TurtlePoint
    end: TurtlePoint


@dataclass(frozen=True)
class TurtleMarkerPoint:
    """One emitted marker point with an unambiguous spatial orientation frame."""

    position: TurtlePoint
    heading: object
    tangent: TurtlePoint
    up: TurtlePoint
    branch_depth: int
    path_id: int
    creation_iteration: int | None
    marker_name: str
    marker_identity: tuple[int, int, int, int]
    parameters: Mapping[str, object]


@dataclass(frozen=True)
class TurtleInterpretation:
    """Static turtle interpretation output: curve segments plus marker points."""

    segments: tuple[TurtleSegment, ...]
    markers: tuple[TurtleMarkerPoint, ...]


__all__ = [
    "LSystemAnalysis",
    "TurtlePoint",
    "TurtleFrame",
    "TurtleSegment",
    "TurtleMarkerPoint",
    "TurtleInterpretation",
]
