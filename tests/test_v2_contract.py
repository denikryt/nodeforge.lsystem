"""Pure-Python contract regressions for the L-System Extension API v2 migration."""

from __future__ import annotations

import json

from pathlib import Path

import pytest

from NodeForge import packages
from NodeForge.errors import CompileError
from NodeForge.evaluation_modes import EvaluationMode
from NodeForge.extension_registry import ExtensionOwnerSession, capture_owner_code_snapshot
from NodeForge.nf_types import NFType


ROOT = Path(__file__).resolve().parents[1]
OWNER = ROOT / "systems" / "lsystem"
OWNER_KEY = ("system", "nodeforge.lsystem", "lsystem")


def _session():
    """Return one fresh owner session over the migrated package snapshot."""
    return ExtensionOwnerSession(capture_owner_code_snapshot(OWNER_KEY, OWNER))


def _callable_id(session, name):
    """Return the canonical callable id for one public L-System name."""
    families, _refs = session.normalize_interface()
    return next(callable_id for callable_id in families if callable_id.name == name)


def test_interface_declares_complete_v2_inventory_and_execution_forms():
    """All nine public callables normalize through one declaration-only v2 interface."""
    session = _session()
    families, refs = session.normalize_interface()
    by_name = {callable_id.name: callable_id for callable_id in families}
    assert set(by_name) == {
        "ls_axiom", "ls_rule", "ls_iterations", "ls_angle", "ls_step",
        "ls_param", "ls_marker", "ls_system", "ls_points",
    }
    for name in {"ls_axiom", "ls_rule", "ls_iterations", "ls_angle", "ls_step", "ls_param", "ls_marker"}:
        assert refs[by_name[name]] is None
        assert session.semantic_return_type(by_name[name]).kind == "RECORD"
    assert refs[by_name["ls_system"]].module == ".backend"
    assert refs[by_name["ls_system"]].attribute == "ls_system"
    assert session.semantic_return_type(by_name["ls_system"]).record_type.name == "_LSystemSpec"
    assert refs[by_name["ls_points"]].attribute == "ls_points"
    assert session.semantic_return_type(by_name["ls_points"]) is None


def test_interface_rejects_runtime_marker_name_and_uses_normalized_binding_modes():
    """Static/runtime requirements are part of the common v2 callable contract, not package AST parsing."""
    session = _session()
    families, _refs = session.normalize_interface()
    by_name = {callable_id.name: specs[0] for callable_id, specs in families.items()}
    marker = by_name["ls_marker"]
    assert marker.parameters[0].evaluation_mode is EvaluationMode.COMPILE_TIME_ONLY
    assert marker.parameters[1].kind.name == "VAR_POSITIONAL"
    assert marker.parameters[1].evaluation_mode is EvaluationMode.COMPILE_TIME_ONLY
    points = by_name["ls_points"]
    assert points.parameters[0].evaluation_mode is EvaluationMode.RUNTIME_ONLY
    assert points.parameters[1].evaluation_mode is EvaluationMode.COMPILE_TIME_ONLY
    assert points.parameters[1].kind.name == "KEYWORD_ONLY"
    assert points.parameters[0].type_spec.nf_types == frozenset({NFType.GEOMETRY})


def test_semantic_constructors_and_ls_system_normalize_one_private_spec():
    """Constructor records compose into the single declared private semantic specification."""
    session = _session()
    axiom = session.invoke_semantic(_callable_id(session, "ls_axiom"), "F(length)Leaf(length)")
    rule = session.invoke_semantic(_callable_id(session, "ls_rule"), "F", "F+F")
    iterations = session.invoke_semantic(_callable_id(session, "ls_iterations"), 2)
    angle = session.invoke_semantic(_callable_id(session, "ls_angle"), 25.0)
    step = session.invoke_semantic(_callable_id(session, "ls_step"), 1.0)
    param = session.invoke_semantic(_callable_id(session, "ls_param"), "length", 2.0)
    marker = session.invoke_semantic(_callable_id(session, "ls_marker"), "Leaf", "length")
    spec = session.invoke_semantic(
        _callable_id(session, "ls_system"),
        axiom,
        rule,
        iterations,
        angle,
        step,
        param,
        marker,
    )
    assert type(spec).__name__ == "_LSystemSpec"
    assert spec.iterations == 2
    assert spec.params == {"length": 2.0}
    assert tuple(module.name for module in spec.axiom) == ("F", "Leaf")
    assert spec.axiom[0].args[0].param_name == "length"
    assert not hasattr(spec.axiom[0].args[0], "is_runtime")
    assert spec.markers["Leaf"].parameter_names == ("length",)


def test_semantic_normalization_rejects_duplicate_or_missing_required_parts():
    """The semantic normalization authority rejects invalid aggregate specs before backend dispatch."""
    session = _session()
    cid = lambda name: _callable_id(session, name)
    axiom = session.invoke_semantic(cid("ls_axiom"), "F")
    iterations = session.invoke_semantic(cid("ls_iterations"), 1)
    angle = session.invoke_semantic(cid("ls_angle"), 25.0)
    step = session.invoke_semantic(cid("ls_step"), 1.0)
    with pytest.raises(CompileError, match="duplicate ls_axiom"):
        session.invoke_semantic(cid("ls_system"), axiom, axiom, iterations, angle, step)
    with pytest.raises(CompileError, match=r"requires ls_step"):
        session.invoke_semantic(cid("ls_system"), axiom, iterations, angle)


def test_marker_semantics_preserve_identity_and_reject_reserved_or_duplicate_parameters():
    """Marker metadata stays deterministic while invalid marker declarations remain package errors."""
    session = _session()
    marker_id = _callable_id(session, "ls_marker")
    first = session.invoke_semantic(marker_id, "Leaf", "size", "age")
    second = session.invoke_semantic(marker_id, "Leaf", "size", "age")
    assert first.marker_identity == second.marker_identity
    assert first.parameter_names == ("size", "age")
    with pytest.raises(CompileError, match="built-in"):
        session.invoke_semantic(marker_id, "F")
    with pytest.raises(CompileError, match="duplicate parameter"):
        session.invoke_semantic(marker_id, "Leaf", "size", "size")
    with pytest.raises(CompileError, match="reserved nf_lsys_ prefix"):
        session.invoke_semantic(marker_id, "Leaf", "nf_lsys_bad")


def test_package_semantic_source_has_no_compiler_or_backend_carrier_dependency():
    """Semantic package modules stay detached from compiler/backend implementation objects."""
    source = "\n".join(
        (OWNER / name).read_text(encoding="utf-8")
        for name in ("interface.py", "semantic.py", "modules.py", "model.py")
    )
    forbidden = (
        "NodeForge.values", "NodeForge.nodes", "NodeForge.compiler", "CompileTimeObject",
        "ExtensionBackendValue", "BindingId", "ast.Call",
    )
    for token in forbidden:
        assert token not in source


def test_lsystem_23_manifest_accepts_nodeforge_0622():
    """The v2 L-System 2.3 artifact accepts the legacy-free NodeForge 0.62.2 release."""
    manifest = packages.validate_package_root(ROOT)
    raw = json.loads((ROOT / "nodeforge_package.json").read_text(encoding="utf-8"))
    assert manifest.version == "2.3"
    assert raw["nodeforge_min_version"] == "0.62.0"
    assert raw["nodeforge_max_version"] == "0.62.2"


def test_stage36_negative_manifest_no_longer_caps_at_nodeforge_0621():
    """The coordinated L-System artifact cannot remain pinned to the pre-cutover core patch."""
    raw = json.loads((ROOT / "nodeforge_package.json").read_text(encoding="utf-8"))
    assert raw["nodeforge_max_version"] != "0.62.1"
