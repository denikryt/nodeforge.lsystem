"""Declarative Extension API v2 contract for the NodeForge L-System package."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from NodeForge import EvaluationMode, Float, Geometry, Int, String


STATIC = EvaluationMode.COMPILE_TIME_ONLY
MIXED = EvaluationMode.COMPILE_TIME_OR_RUNTIME
RUNTIME = EvaluationMode.RUNTIME_ONLY
Numeric = Float | Int

EXTENSION_API = 2

EXTENSIONS = {
    "ls_axiom": None,
    "ls_rule": None,
    "ls_iterations": None,
    "ls_angle": None,
    "ls_step": None,
    "ls_param": None,
    "ls_marker": None,
    "ls_system": ".backend:ls_system",
    "ls_points": ".backend:ls_points",
}


@dataclass(frozen=True)
class LSystemPart:
    """Nominal base record accepted by ``ls_system(*parts)``."""


@dataclass(frozen=True)
class LSystemAxiom(LSystemPart):
    """Validated compile-time axiom source."""

    value: str


@dataclass(frozen=True)
class LSystemRule(LSystemPart):
    """Validated one-symbol rewrite rule."""

    symbol: str
    replacement: str


@dataclass(frozen=True)
class LSystemIterations(LSystemPart):
    """Static or runtime NodeForge Int rewrite count."""

    value: Int


@dataclass(frozen=True)
class LSystemAngle(LSystemPart):
    """Static or runtime numeric turn angle in degrees."""

    value: Numeric


@dataclass(frozen=True)
class LSystemStep(LSystemPart):
    """Static or runtime numeric forward distance."""

    value: Numeric


@dataclass(frozen=True)
class LSystemParam(LSystemPart):
    """Named static/runtime numeric parameter available in module strings."""

    name: str
    value: Numeric


@dataclass(frozen=True)
class LSystemMarker(LSystemPart):
    """Declared marker module and stable package-domain marker identity."""

    name: str
    parameter_names: tuple[str, ...]
    marker_identity: tuple[int, int, int, int]


@dataclass(frozen=True)
class _ModuleArg:
    """Normalized package-private module argument stored in semantic state."""

    source: str
    value: Numeric
    param_name: str | None = None


@dataclass(frozen=True)
class _Module:
    """One parsed package-private L-System module token."""

    name: str
    args: tuple[_ModuleArg, ...] = ()
    raw: str = ""


@dataclass(frozen=True)
class _LSystemSpec:
    """Complete private semantic state reconstructed for physical realization."""

    axiom: tuple[_Module, ...]
    rules: dict[str, tuple[_Module, ...]]
    iterations: Int
    angle: Numeric
    step: Numeric
    params: dict[str, Numeric]
    markers: dict[str, LSystemMarker]


def ls_axiom(value: Annotated[String, STATIC]) -> LSystemAxiom:
    """Declare and validate one compile-time L-System axiom."""
    ...


def ls_rule(
    symbol: Annotated[String, STATIC],
    replacement: Annotated[String, STATIC],
) -> LSystemRule:
    """Declare one validated single-symbol rewrite rule."""
    ...


def ls_iterations(value: Annotated[Int, MIXED]) -> LSystemIterations:
    """Declare a static or runtime rewrite-iteration count."""
    ...


def ls_angle(value: Annotated[Numeric, MIXED]) -> LSystemAngle:
    """Declare a static or runtime turn angle in degrees."""
    ...


def ls_step(value: Annotated[Numeric, MIXED]) -> LSystemStep:
    """Declare a static or runtime forward step distance."""
    ...


def ls_param(
    name: Annotated[String, STATIC],
    value: Annotated[Numeric, MIXED],
) -> LSystemParam:
    """Declare one named static/runtime numeric module parameter."""
    ...


def ls_marker(
    name: Annotated[String, STATIC],
    *parameter_names: Annotated[String, STATIC],
) -> LSystemMarker:
    """Declare one marker module and its exported parameter names."""
    ...


def ls_system(*parts: LSystemPart) -> Geometry:
    """Build Geometry from normalized L-System constructor records."""
    ...


def ls_points(
    geometry: Annotated[Geometry, RUNTIME],
    *,
    marker: Annotated[String, STATIC],
) -> Geometry:
    """Extract points associated with one compile-time marker name."""
    ...
