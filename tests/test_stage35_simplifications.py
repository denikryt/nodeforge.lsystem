"""Regression coverage for the Stage 35 Blender-5.2 backend simplification."""

from __future__ import annotations

import importlib.util
import inspect
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from NodeForge.errors import CompileError
from NodeForge.nf_types import NFType
from systems.lsystem import backends


ROOT = Path(__file__).resolve().parents[1]
LSYSTEM = ROOT / "systems" / "lsystem"


class _GetOnlySockets:
    """Socket collection that makes accidental compatibility probing observable."""

    def __init__(self, mapping):
        self._mapping = dict(mapping)
        self.get_calls = []

    def get(self, name):
        self.get_calls.append(name)
        return self._mapping.get(name)

    def __getitem__(self, _key):  # pragma: no cover - must never be reached
        raise AssertionError("socket fallback indexing is forbidden")

    def __iter__(self):  # pragma: no cover - must never be reached
        raise AssertionError("socket fallback iteration is forbidden")


def _load_resources(monkeypatch, bpy_module):
    """Load resources.py with an explicit fake bpy module."""
    monkeypatch.setitem(sys.modules, "bpy", bpy_module)
    module_name = "_stage35_resources_test"
    sys.modules.pop(module_name, None)
    spec = importlib.util.spec_from_file_location(module_name, LSYSTEM / "resources.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


# Simplification invariant A — marker runtime dependencies are explicit arguments,
# not one-off structural pseudo-types.
def test_stage35_simplification_marker_params_have_explicit_dependencies():
    parameters = inspect.signature(backends._store_runtime_marker_params).parameters
    assert tuple(parameters) == (
        "context",
        "geometry",
        "marker_parameter_names",
        "runtime_params",
        "x",
        "y",
    )


def test_stage35_simplification_marker_param_pseudo_types_are_absent():
    source = (LSYSTEM / "backends.py").read_text(encoding="utf-8") + (LSYSTEM / "runtime_dynamic.py").read_text(encoding="utf-8")
    assert "StaticMarkerParamTable" not in source
    assert "DynamicMarkerParamTable" not in source


# Simplification invariant B — Blender 5.2 socket contracts are direct and fail-fast.
def test_stage35_simplification_socket_lookup_uses_blender_52_name_contract():
    expected = object()
    sockets = _GetOnlySockets({"Geometry": expected})
    node = SimpleNamespace(bl_idname="GeometryNodeStoreNamedAttribute")
    assert backends._socket_by_name(sockets, "Geometry", node=node, direction="input") is expected
    assert sockets.get_calls == ["Geometry"]


def test_stage35_simplification_missing_blender_52_socket_is_error_without_fallback():
    sockets = _GetOnlySockets({})
    node = SimpleNamespace(bl_idname="GeometryNodeStoreNamedAttribute")
    with pytest.raises(CompileError, match="Blender 5.2 contract"):
        backends._socket_by_name(sockets, "Geometry", node=node, direction="input")
    assert sockets.get_calls == ["Geometry"]


# Simplification invariant C — context.value() is the sole raw-socket -> extension-value boundary.
def test_stage35_simplification_backend_wraps_outputs_through_context_value():
    output = SimpleNamespace(default_value=None)
    node = SimpleNamespace(outputs=[output], location=None, label=None, integer=None)
    created = []
    wrapped = []

    class _Nodes:
        def new(self, bl_idname):
            created.append(bl_idname)
            return node

    context = SimpleNamespace(
        group=SimpleNamespace(nodes=_Nodes()),
        value=lambda socket, typ: wrapped.append((socket, typ)) or (socket, typ),
    )

    result = backends._int_value(context, 7)
    assert created == ["FunctionNodeInputInt"]
    assert wrapped == [(output, NFType.INT)]
    assert result == (output, NFType.INT)


def test_stage35_simplification_backend_has_no_direct_extension_value_construction():
    for filename in ("backends.py", "runtime_dynamic.py"):
        source = (LSYSTEM / filename).read_text(encoding="utf-8")
        assert "ExtensionBackendValue(" not in source
        assert "context.value(" in source


# Simplification invariant D — generated-resource writes use the direct Blender 5.2
# bulk-write contract and propagate physical API errors to the outer transaction.
def test_stage35_simplification_attribute_bulk_write_is_direct(monkeypatch):
    resources = _load_resources(monkeypatch, SimpleNamespace())

    class _Data:
        def __init__(self):
            self.calls = []

        def __len__(self):
            return 2

        def foreach_set(self, field, values):
            self.calls.append((field, tuple(values)))

    scalar_data = _Data()
    resources._write_attribute_values(
        SimpleNamespace(name="weight", data_type="FLOAT", data=scalar_data),
        [1.0, 2.0],
    )
    assert scalar_data.calls == [("value", (1.0, 2.0))]

    vector_data = _Data()
    resources._write_attribute_values(
        SimpleNamespace(name="direction", data_type="FLOAT_VECTOR", data=vector_data),
        [(1.0, 2.0, 3.0), (4.0, 5.0, 6.0)],
    )
    assert vector_data.calls == [("vector", (1.0, 2.0, 3.0, 4.0, 5.0, 6.0))]


def test_stage35_simplification_attribute_bulk_write_propagates_blender_error(monkeypatch):
    resources = _load_resources(monkeypatch, SimpleNamespace())

    class _Data:
        def __len__(self):
            return 1

        def foreach_set(self, _field, _values):
            raise RuntimeError("blender write failed")

    attribute = SimpleNamespace(name="weight", data_type="FLOAT", data=_Data())
    with pytest.raises(RuntimeError, match="blender write failed"):
        resources._write_attribute_values(attribute, [1.0])


# Simplification invariant E — documented generated-object properties are assigned
# directly; setter failures are not swallowed.
def test_stage35_simplification_generated_object_properties_are_direct(monkeypatch):
    resources = _load_resources(monkeypatch, SimpleNamespace())
    obj = SimpleNamespace(hide_viewport=False, hide_render=False, hide_select=False, use_fake_user=True)
    resources._hide_generated_object(obj)
    assert (obj.hide_viewport, obj.hide_render, obj.hide_select, obj.use_fake_user) == (True, True, True, False)


def test_stage35_simplification_generated_object_property_error_propagates(monkeypatch):
    resources = _load_resources(monkeypatch, SimpleNamespace())

    class _RejectingObject:
        def __setattr__(self, name, value):
            if name == "hide_render":
                raise RuntimeError("blender property failed")
            object.__setattr__(self, name, value)

    with pytest.raises(RuntimeError, match="blender property failed"):
        resources._hide_generated_object(_RejectingObject())


def test_stage35_simplification_backend_contains_no_version_fallback_control_flow():
    for filename in ("backends.py", "runtime_dynamic.py", "resources.py"):
        source = (LSYSTEM / filename).read_text(encoding="utf-8")
        assert not re.search(r"(?m)^\s*try\s*:", source)
        assert not re.search(r"(?m)^\s*except(?:\s+[^:]*)?\s*:", source)
