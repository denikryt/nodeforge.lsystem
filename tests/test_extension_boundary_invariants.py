"""Positive and negative regressions for the L-System Extension API v2 cutover."""

from __future__ import annotations

import dataclasses
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import NodeForge
from NodeForge.blender_extension_backend import _validate_result
from NodeForge.compiler_identities import GroupCompilationIdentity
from NodeForge.errors import CompileError
from NodeForge.extension_api import ExtensionBackendValue
from NodeForge.extension_contracts import TypeSpec
from NodeForge.extension_registry import ExtensionOwnerSession, ExtensionRegistry, capture_owner_code_snapshot
from NodeForge.extension_semantic_api import RuntimeRef
from NodeForge.extension_values import ExtensionDependencySlot, ExtensionValue, pack_value, unpack_value
from NodeForge.nf_types import NFType
from NodeForge.resolved_environment import (
    PackageCallableExport,
    ResolvedCatalog,
    ResolvedEnvironment,
    ResolvedPackageNamespace,
)
from NodeForge.semantic_group import analyze_group_source
from NodeForge.semantic_ir import IRCall, IRCallableKind


ROOT = Path(__file__).resolve().parents[1]
OWNER = ROOT / "systems" / "lsystem"
OWNER_KEY = ("system", "nodeforge.lsystem", "lsystem")
CORE = Path(NodeForge.__file__).resolve().parent


def _session() -> ExtensionOwnerSession:
    """Return one coherent current-session view of the migrated L-System owner."""
    return ExtensionOwnerSession(capture_owner_code_snapshot(OWNER_KEY, OWNER))


def _registry_environment():
    """Return one current-session registry/environment over the real L-System owner."""
    session = _session()
    registry = ExtensionRegistry((session,))
    families, _ = session.normalize_interface()
    by_name = {callable_id.name: callable_id for callable_id in families}
    exports = {
        name: PackageCallableExport(
            "nodeforge.lsystem",
            name,
            extension_callable_id=callable_id,
        )
        for name, callable_id in by_name.items()
    }
    namespace = ResolvedPackageNamespace(
        "nodeforge.lsystem",
        "lsystem",
        "NodeForge L-System",
        "3.0.1",
        exports,
    )
    environment = ResolvedEnvironment(
        {name: ResolvedCatalog(name, {}) for name in ("functions", "examples", "local")},
        package_namespaces={"nodeforge.lsystem": namespace},
        extension_registry=registry,
    )
    return session, registry, by_name, environment


def _identity(suffix: str) -> GroupCompilationIdentity:
    """Return one isolated root compilation identity for a pure semantic regression."""
    owner = f"ROOT/extension_boundary/{suffix}"
    return GroupCompilationIdentity(None, owner, owner, owner)


def _find_ir_calls(body):
    """Return all direct IRCall operations recursively visible in statement value programs."""
    calls = []
    for statement in body.statements:
        program = getattr(statement, "value", None)
        if program is not None:
            calls.extend(op for op in program.operations if isinstance(op, IRCall))
    return calls


# Invariant 1 — v2 interface is the only supported L-System Python-extension entry.
def test_v2_interface_is_complete():
    session = _session()
    families, _ = session.normalize_interface()
    assert {callable_id.name for callable_id in families} == {
        "axiom", "rule", "iterations", "angle", "step",
        "param", "marker", "generate_lsystem", "points",
    }


def test_v1_lsystem_entrypoints_are_absent():
    for obsolete in ("system.py", "constructors.py", "compiler.py"):
        assert not (OWNER / obsolete).exists(), obsolete


# Invariant 2 — semantic state contains only declared detached values/RuntimeRef.
def test_semantic_record_packs_runtime_ref():
    session, registry, by_name, _environment = _registry_environment()
    token = object()
    runtime = RuntimeRef(token, NFType.FLOAT)
    record = session.invoke_semantic(by_name["angle"], runtime)
    spec = session.semantic_return_type(by_name["angle"])
    packed = pack_value(spec, record, registry=registry, active_runtime_refs={token: (0, NFType.FLOAT)})
    assert isinstance(packed, ExtensionValue)
    assert packed.storage == (ExtensionDependencySlot(0, NFType.FLOAT),)


def test_backend_value_cannot_enter_semantic_storage():
    session, registry, by_name, _environment = _registry_environment()
    backend_value = ExtensionBackendValue(object(), NFType.FLOAT)
    record = session.invoke_semantic(by_name["angle"], backend_value)
    spec = session.semantic_return_type(by_name["angle"])
    with pytest.raises(CompileError, match="Unsupported detached NodeForge value"):
        pack_value(spec, record, registry=registry, active_runtime_refs={})


# Invariant 3 — backend reconstruction replaces runtime semantic slots with ExtensionBackendValue.
def test_backend_reconstruction_uses_backend_values():
    session, registry, by_name, _environment = _registry_environment()
    token = object()
    semantic_runtime = RuntimeRef(token, NFType.FLOAT)
    record = session.invoke_semantic(by_name["angle"], semantic_runtime)
    spec = session.semantic_return_type(by_name["angle"])
    packed = pack_value(spec, record, registry=registry, active_runtime_refs={token: (0, NFType.FLOAT)})
    physical = ExtensionBackendValue(object(), NFType.FLOAT)
    reconstructed = unpack_value(
        spec,
        packed,
        registry=registry,
        runtime_leaf_resolver=lambda stored: (NFType.FLOAT, physical)
        if isinstance(stored, ExtensionDependencySlot)
        else None,
    )
    assert reconstructed.value is physical


def test_backend_module_has_no_semantic_or_compiler_carriers():
    source = (OWNER / "backend.py").read_text(encoding="utf-8")
    for forbidden in ("RuntimeRef", "BindingId", "Compiler", "ast.Call", "NodeForge.values.Value"):
        assert forbidden not in source


# Invariant 4 — semantic generate_lsystem is the single package normalization authority.
def test_ls_system_returns_declared_private_spec():
    session, _registry, by_name, _environment = _registry_environment()
    parts = [
        session.invoke_semantic(by_name["axiom"], "F"),
        session.invoke_semantic(by_name["iterations"], 2),
        session.invoke_semantic(by_name["angle"], 25),
        session.invoke_semantic(by_name["step"], 1),
    ]
    spec = session.invoke_semantic(by_name["generate_lsystem"], *parts)
    assert type(spec).__name__ == "_LSystemSpec"
    assert spec.angle == 25.0 and spec.step == 1.0


def test_parallel_legacy_semantic_authority_is_absent():
    semantic_source = (OWNER / "semantic.py").read_text(encoding="utf-8")
    assert "def generate_lsystem" in semantic_source
    assert "CompileTimeObject" not in semantic_source
    assert not (OWNER / "compiler.py").exists()


# Invariant 5 — persistence is generic body state, including generic Repeat rejection.
def test_constructor_part_persists_through_source_variable():
    _session_obj, _registry, _by_name, environment = _registry_environment()
    compilation = analyze_group_source(
        'from packages import lsystem\n'
        'a = input_float("Angle")\npart = angle(a)\ngeo = generate_lsystem(axiom("F"), iterations(1), part, step(1))\noutput(geo)\n',
        compilation_identity=_identity("persist"),
        resolved_environment=environment,
    )
    assert compilation.body is not None
    extension_calls = [call for call in _find_ir_calls(compilation.body) if call.target.kind is IRCallableKind.EXTENSION]
    ls_system_call = next(call for call in extension_calls if call.target.name == "generate_lsystem")
    assert ls_system_call.extension_state is not None


def test_repeat_cannot_carry_extension_semantic_value():
    _session_obj, _registry, _by_name, environment = _registry_environment()
    with pytest.raises(CompileError, match="repeat_range cannot carry or rebind package semantic value 'part'"):
        analyze_group_source(
            'from packages import lsystem\n'
            'a = input_float("Angle")\npart = angle(a)\nfor i in repeat_range(2):\n    part = part\noutput(a)\n',
            compilation_identity=_identity("repeat_reject"),
            resolved_environment=environment,
        )



def test_semantic_part_list_literal_star_uses_generic_semantic_list_path():
    """Sibling L-System part records can form a semantic list and expand into generate_lsystem()."""
    _session_obj, _registry, _by_name, environment = _registry_environment()
    compilation = analyze_group_source(
        'from packages import lsystem\n'
        'parts = [\n'
        '    axiom("F"),\n'
        '    iterations(2),\n'
        '    angle(25),\n'
        '    step(1),\n'
        ']\n'
        'geo = generate_lsystem(*parts)\n'
        'output(geo)\n',
        compilation_identity=_identity("semantic_list_direct"),
        resolved_environment=environment,
    )
    extension_calls = [call for call in _find_ir_calls(compilation.body) if call.target.kind is IRCallableKind.EXTENSION]
    assert any(call.target.name == "generate_lsystem" for call in extension_calls)


def test_semantic_part_list_literal_preserves_persistent_runtime_dependency():
    """Assigned L-System records keep runtime dependencies when collected then expanded from a semantic list."""
    _session_obj, _registry, _by_name, environment = _registry_environment()
    compilation = analyze_group_source(
        'from packages import lsystem\n'
        'runtime_angle = input_float("Angle")\n'
        'axiom = axiom("F")\n'
        'angle = angle(runtime_angle)\n'
        'parts = [axiom, iterations(2), angle, step(1)]\n'
        'geo = generate_lsystem(*parts)\n'
        'output(geo)\n',
        compilation_identity=_identity("semantic_list_persistent"),
        resolved_environment=environment,
    )
    extension_calls = [call for call in _find_ir_calls(compilation.body) if call.target.kind is IRCallableKind.EXTENSION]
    ls_system_call = next(call for call in extension_calls if call.target.name == "generate_lsystem")
    assert len(ls_system_call.arguments) == 1
    assert ls_system_call.arguments[0].value.typ is NFType.FLOAT

# Invariant 6 — carrier identity, not a duplicate is_runtime flag, encodes dynamic/static leaves.
def test_static_and_runtime_carriers_are_distinct():
    session, _registry, by_name, _environment = _registry_environment()
    static = session.invoke_semantic(by_name["step"], 2)
    token = object()
    runtime = RuntimeRef(token, NFType.INT)
    dynamic = session.invoke_semantic(by_name["step"], runtime)
    assert static.value == 2.0 and type(static.value) is float
    assert dynamic.value is runtime


def test_cross_boundary_records_have_no_is_runtime_field():
    session = _session()
    session.normalize_interface()
    for name in ("_ModuleArg", "_Module", "_LSystemSpec", "LSystemAngle", "LSystemStep", "LSystemParam"):
        cls = next(cls for cls in session._type_ids_by_class if cls.__name__ == name)
        assert "is_runtime" not in {field.name for field in dataclasses.fields(cls)}


# Invariant 7 — generated external Blender IDs are owned at allocation by context services.
def test_resources_use_context_owned_creation():
    source = (OWNER / "resources.py").read_text(encoding="utf-8")
    assert "context.new_generated_mesh(" in source
    assert "context.new_generated_object(" in source
    assert source.count('(\"nf_lsys_path_depth\", \"INT\", table.path_depth)') == 1


def test_resources_do_not_create_then_register_or_rollback():
    source = (OWNER / "resources.py").read_text(encoding="utf-8")
    for forbidden in ("bpy.data.meshes.new", "bpy.data.objects.new", "transaction.add", ".rollback(", "generated_resources"):
        assert forbidden not in source


# Invariant 8 — physical package backend has no Compiler escape hatch.
def test_backend_uses_public_extension_context_and_values():
    source = (OWNER / "backend.py").read_text(encoding="utf-8")
    assert "ExtensionBackendValue" in source
    assert "def ls_system(context, spec)" in source
    assert "def ls_points(context, geometry, *, marker)" in source


def test_package_production_has_no_private_compiler_backend_imports():
    forbidden = (
        "NodeForge.compiler", "NodeForge.values", "NodeForge.nodes", "NodeForge.geometry",
        "NodeForge.generated_resources", "NodeForge.compile_time", "Compiler.compile(", "comp.compile(",
    )
    for path in OWNER.glob("*.py"):
        source = path.read_text(encoding="utf-8")
        for token in forbidden:
            assert token not in source, (path.name, token)


# Invariant 9 — domain algorithms remain package-owned; core remains generic.
def test_domain_algorithms_remain_in_lsystem_package():
    for module in ("analysis.py", "expander.py", "modules.py", "runtime_tables.py", "runtime_dynamic.py", "turtle.py"):
        assert (OWNER / module).is_file()


def test_nodeforge_core_has_no_lsystem_special_case():
    offenders = []
    for path in CORE.glob("*.py"):
        source = path.read_text(encoding="utf-8")
        if "LSystem" in source or "lsystem" in source.lower():
            offenders.append(path.name)
    assert offenders == []


# Invariant 10 — supported L-System uses ordinary EXTENSION Call IR and v1 executors are gone.
def test_ls_system_is_ordinary_extension_ir_call():
    _session_obj, _registry, _by_name, environment = _registry_environment()
    compilation = analyze_group_source(
        'from packages import lsystem\n'
        'geo = generate_lsystem(axiom("F"), iterations(1), angle(25), step(1))\noutput(geo)\n',
        compilation_identity=_identity("extension_ir"),
        resolved_environment=environment,
    )
    call = next(call for call in _find_ir_calls(compilation.body) if call.target.name == "generate_lsystem")
    assert call.target.kind is IRCallableKind.EXTENSION


def test_v1_execution_entrypoints_are_unavailable():
    assert not (CORE / "systems" / "registry.py").exists()
    library_source = (CORE / "library.py").read_text(encoding="utf-8")
    for name in ("compile_module_library_entry_call", "compile_module_library_entry_call_resolved"):
        assert f"def {name}(" not in library_source


# Invariant 11 — pure source/native v2 remain separate while source+interface hybrid stays blocked.
def test_pure_source_path_remains_present():
    source = (CORE / "source_callables.py").read_text(encoding="utf-8")
    assert "class SourceCallableSession" in source
    assert "analyze_group_source" in (CORE / "semantic_group.py").read_text(encoding="utf-8")


def test_hybrid_v2_remains_explicitly_blocked():
    library_source = (CORE / "library.py").read_text(encoding="utf-8")
    semantic_source = (CORE / "semantic_analysis.py").read_text(encoding="utf-8")
    marker = "Source-backed library owners with interface.py are reserved for the"
    assert marker in library_source
    assert "hybrid" in semantic_source.lower() and "TODO(nodeforge-migration)" in semantic_source


# Invariant 12 — generic backend result validation is the authority.
def test_declared_geometry_result_accepts_backend_wrapper(monkeypatch):
    import NodeForge.blender_extension_backend as extension_backend

    monkeypatch.setattr(extension_backend, "validate_runtime_value_socket", lambda *_args, **_kwargs: None)
    spec = TypeSpec("NF_SET", nf_types=frozenset({NFType.GEOMETRY}))
    socket = object()
    value = _validate_result(ExtensionBackendValue(socket, NFType.GEOMETRY), spec, SimpleNamespace(group=object()))
    assert value.socket is socket and value.typ is NFType.GEOMETRY


def test_raw_or_wrong_typed_backend_result_is_rejected(monkeypatch):
    import NodeForge.blender_extension_backend as extension_backend

    monkeypatch.setattr(extension_backend, "validate_runtime_value_socket", lambda *_args, **_kwargs: None)
    spec = TypeSpec("NF_SET", nf_types=frozenset({NFType.GEOMETRY}))
    context = SimpleNamespace(group=object())
    with pytest.raises(CompileError, match="must return ExtensionBackendValue"):
        _validate_result(object(), spec, context)
    with pytest.raises(CompileError, match="returned FLOAT, expected GEOMETRY"):
        _validate_result(ExtensionBackendValue(object(), NFType.FLOAT), spec, context)


# Invariant 13 — marker identity/schema behavior remains package-domain behavior.
def test_marker_identity_is_stable_and_declared(monkeypatch):
    session, _registry, by_name, _environment = _registry_environment()
    first = session.invoke_semantic(by_name["marker"], "Leaf", "size")
    second = session.invoke_semantic(by_name["marker"], "Leaf", "size")
    assert first.marker_identity == second.marker_identity
    assert first.parameter_names == ("size",)

    monkeypatch.setitem(sys.modules, "bpy", SimpleNamespace())
    from systems.lsystem import backend as lsystem_backend

    seen = {}
    monkeypatch.setattr(
        lsystem_backend,
        "filter_marker_points",
        lambda context, geometry, marker, *, x, y: seen.setdefault("marker", marker) or geometry,
    )
    context = SimpleNamespace(location=(10, 20))
    geometry = ExtensionBackendValue(object(), NFType.GEOMETRY)
    lsystem_backend.ls_points(context, geometry, marker="Leaf")
    assert seen["marker"] == "Leaf"


def test_invalid_marker_forms_remain_package_errors(monkeypatch):
    session, _registry, by_name, _environment = _registry_environment()
    with pytest.raises(CompileError, match="collides with a built-in"):
        session.invoke_semantic(by_name["marker"], "F")
    with pytest.raises(CompileError, match="duplicate parameter"):
        session.invoke_semantic(by_name["marker"], "Leaf", "size", "size")
    with pytest.raises(CompileError, match="reserved nf_lsys_ prefix"):
        session.invoke_semantic(by_name["marker"], "Leaf", "nf_lsys_private")

    monkeypatch.setitem(sys.modules, "bpy", SimpleNamespace())
    from systems.lsystem import backend as lsystem_backend

    with pytest.raises(CompileError, match=r"points\(\) marker must match"):
        lsystem_backend.ls_points(None, ExtensionBackendValue(object(), NFType.GEOMETRY), marker="bad marker")

    # Collision validation belongs to semantic normalization even though the stable
    # marker hash makes a natural collision impractical to synthesize.
    from systems.lsystem.interface import (
        LSystemAngle, LSystemAxiom, LSystemIterations, LSystemMarker, LSystemStep,
    )
    from systems.lsystem.semantic import generate_lsystem

    identity = (1, 2, 3, 4)
    with pytest.raises(CompileError, match="marker identity collision"):
        generate_lsystem(
            LSystemAxiom("F"),
            LSystemIterations(1),
            LSystemAngle(25.0),
            LSystemStep(1.0),
            LSystemMarker("Leaf", (), identity),
            LSystemMarker("Bud", (), identity),
        )


# Invariant 14 — backend category selection reads backend carriers and retains controlled limits.
def test_backend_category_selection_matches_static_and_runtime_carriers():
    from systems.lsystem.analysis import analyze
    from systems.lsystem.backends import select_backend_category
    from systems.lsystem.interface import _Module

    stream = (_Module("F"),)
    assert select_backend_category(analyze(stream, angle=25.0, step=1.0, markers={})) == "static"
    runtime_step = ExtensionBackendValue(object(), NFType.FLOAT)
    assert select_backend_category(analyze(stream, angle=25.0, step=runtime_step, markers={})) == "branch_free_runtime"


def test_branched_runtime_depth_limit_is_controlled():
    from systems.lsystem.backends import MAX_LSYSTEM_BRANCH_DEPTH, validate_branch_aware_backend_available
    from systems.lsystem.model import LSystemAnalysis

    analysis = LSystemAnalysis(
        has_branches=True,
        angle_is_runtime=True,
        step_is_runtime=False,
        segment_count=1,
        symbol_count=1,
        max_branch_depth=MAX_LSYSTEM_BRANCH_DEPTH + 1,
    )
    with pytest.raises(CompileError, match="MAX_LSYSTEM_BRANCH_DEPTH"):
        validate_branch_aware_backend_available(analysis, "branched_runtime")


# Invariant 15 — the normalized Python signature is the public call-binding authority.
def test_python_signatures_bind_valid_forms():
    session = _session()
    families, _ = session.normalize_interface()
    by_name = {callable_id.name: specs[0] for callable_id, specs in families.items()}
    assert by_name["marker"].python_signature().bind("Leaf", "size", "age").args == ("Leaf", "size", "age")
    bound = by_name["points"].python_signature().bind(object(), marker="Leaf")
    assert bound.arguments["marker"] == "Leaf"


def test_python_signatures_reject_invalid_binding():
    session = _session()
    families, _ = session.normalize_interface()
    by_name = {callable_id.name: specs[0] for callable_id, specs in families.items()}
    with pytest.raises(TypeError):
        by_name["points"].python_signature().bind(object(), "Leaf")
    with pytest.raises(TypeError):
        by_name["rule"].python_signature().bind("F")
    with pytest.raises(TypeError):
        by_name["angle"].python_signature().bind(1, unexpected=True)
