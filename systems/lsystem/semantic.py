"""Frontend semantic normalization for the NodeForge L-System extension."""

from __future__ import annotations

from NodeForge.errors import CompileError

from .interface import (
    LSystemAngle,
    LSystemAxiom,
    LSystemIterations,
    LSystemMarker,
    LSystemParam,
    LSystemPart,
    LSystemRule,
    LSystemStep,
    _LSystemSpec,
)
from .modules import BUILTIN_COMMANDS, marker_identity, parse_stream, validate_identifier
from .validation import validate_rule_symbol, validate_stream


def axiom(value) -> LSystemAxiom:
    """Validate one axiom source and return its public semantic record."""
    return LSystemAxiom(validate_stream(value, "axiom()"))


def rule(symbol, replacement) -> LSystemRule:
    """Validate one one-symbol rewrite rule and return its semantic record."""
    return LSystemRule(
        validate_rule_symbol(symbol),
        validate_stream(replacement, "rule() replacement"),
    )


def iterations(value) -> LSystemIterations:
    """Validate a static non-negative rewrite count while preserving runtime Int refs."""
    if type(value) is int and value < 0:
        raise CompileError("iterations() must be non-negative")
    return LSystemIterations(value)


def _normalize_static_float(value):
    """Preserve the v1 detached-numeric contract while leaving RuntimeRef values intact."""
    return float(value) if type(value) is int else value


def angle(value) -> LSystemAngle:
    """Return the normalized angle semantic record."""
    return LSystemAngle(_normalize_static_float(value))


def step(value) -> LSystemStep:
    """Return the normalized step semantic record."""
    return LSystemStep(_normalize_static_float(value))


def param(name, value) -> LSystemParam:
    """Validate a named numeric parameter and return its semantic record."""
    return LSystemParam(
        validate_identifier(name, "param() name"),
        _normalize_static_float(value),
    )


def marker(name, *parameter_names) -> LSystemMarker:
    """Validate one marker declaration and derive its stable package identity."""
    name = validate_identifier(name, "marker() name")
    if name in BUILTIN_COMMANDS:
        raise CompileError(f"marker() name {name!r} collides with a built-in L-system command")
    normalized: list[str] = []
    seen: set[str] = set()
    for parameter_name in parameter_names:
        parameter_name = validate_identifier(parameter_name, "marker() parameter name")
        if parameter_name in seen:
            raise CompileError(f"marker() received duplicate parameter name {parameter_name!r}")
        if parameter_name.startswith("nf_lsys_"):
            raise CompileError(
                f"marker() parameter name {parameter_name!r} uses reserved nf_lsys_ prefix"
            )
        seen.add(parameter_name)
        normalized.append(parameter_name)
    return LSystemMarker(name, tuple(normalized), marker_identity(name))


def system(*parts) -> _LSystemSpec:
    """Normalize public L-System parts into one complete private backend specification."""
    axiom = None
    iterations = None
    angle = None
    step = None
    raw_rules: dict[str, str] = {}
    params: dict[str, object] = {}
    markers: dict[str, LSystemMarker] = {}
    identities: dict[tuple[int, int, int, int], str] = {}

    for part in parts:
        if not isinstance(part, LSystemPart):
            raise CompileError("system() accepts only L-system constructor parts")
        if isinstance(part, LSystemAxiom):
            if axiom is not None:
                raise CompileError("system() received duplicate axiom()")
            axiom = part.value
        elif isinstance(part, LSystemIterations):
            if iterations is not None:
                raise CompileError("system() received duplicate iterations()")
            iterations = part.value
        elif isinstance(part, LSystemAngle):
            if angle is not None:
                raise CompileError("system() received duplicate angle()")
            angle = part.value
        elif isinstance(part, LSystemStep):
            if step is not None:
                raise CompileError("system() received duplicate step()")
            step = part.value
        elif isinstance(part, LSystemParam):
            if part.name in params:
                raise CompileError(f"system() received duplicate param() for {part.name!r}")
            params[part.name] = part.value
        elif isinstance(part, LSystemMarker):
            if part.name in markers:
                raise CompileError(f"system() received duplicate marker() for {part.name!r}")
            if part.marker_identity in identities:
                raise CompileError(
                    f"system() marker identity collision between "
                    f"{identities[part.marker_identity]!r} and {part.name!r}"
                )
            identities[part.marker_identity] = part.name
            markers[part.name] = part
        elif isinstance(part, LSystemRule):
            if part.symbol in raw_rules:
                raise CompileError(f"system() received duplicate rule for {part.symbol!r}")
            raw_rules[part.symbol] = part.replacement
        else:
            raise CompileError("system() accepts only L-system constructor parts")

    if axiom is None:
        raise CompileError("system() requires axiom(...)")
    if iterations is None:
        raise CompileError("system() requires iterations(...)")
    if angle is None:
        raise CompileError("system() requires angle(...)")
    if step is None:
        raise CompileError("system() requires step(...)")

    parsed_axiom = parse_stream(axiom, params=params, markers=markers, context="axiom()")
    parsed_rules = {
        symbol: parse_stream(
            replacement,
            params=params,
            markers=markers,
            context="rule() replacement",
        )
        for symbol, replacement in raw_rules.items()
    }
    return _LSystemSpec(
        axiom=parsed_axiom,
        rules=parsed_rules,
        iterations=iterations,
        angle=angle,
        step=step,
        params=dict(params),
        markers=dict(markers),
    )
