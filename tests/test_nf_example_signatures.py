"""Source-level regression checks for typed L-System examples on NodeForge 0.90.2."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest


EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
EXPECTED = {
    "dragon_curve": (("Angle", "Step"), ("Geometry",)),
    "fractal_plant": (("Angle", "Step"), ("Geometry",)),
    "koch_curve": (("Angle", "Step"), ("Geometry",)),
    "marker_points": (("Size",), ("Geometry",)),
    "parametric_modules": (("Length", "Turn"), ("Geometry",)),
    "spatial_plant": (
        ("Growth Iterations", "Branch Angle", "Node Rotation", "Step"),
        ("Geometry", "Leaf Points"),
    ),
}

EXPECTED_PARAMS = {
    "dragon_curve": (("Float", 90.0), ("Float", 0.04)),
    "fractal_plant": (("Float", 25.0), ("Float", 0.04)),
    "koch_curve": (("Float", 60.0), ("Float", 0.08)),
    "marker_points": (("Float", 0.5),),
    "parametric_modules": (("Float", 2.0), ("Float", 90.0)),
    "spatial_plant": (("Int", 5), ("Float", 35.0), ("Float", 137.507764), ("Float", 0.2)),
}


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_example_exports_one_typed_function_with_original_socket_names(name):
    """Each example preserves its public input/output layout under the typed DSL."""
    tree = ast.parse((EXAMPLES / f"{name}.nf").read_text(encoding="utf-8"))
    definitions = [statement for statement in tree.body if isinstance(statement, ast.FunctionDef)]
    assert len(definitions) == 1 and definitions[0].name == name
    assert all(isinstance(statement, (ast.FunctionDef, ast.ImportFrom)) for statement in tree.body)
    fn = definitions[0]
    assert isinstance(fn.body[-1], ast.Return)
    assert len(fn.args.args) == len(fn.args.defaults)

    names = []
    for arg in fn.args.args:
        assert isinstance(arg.annotation, ast.Subscript)
        names.append(ast.literal_eval(arg.annotation.slice))
    assert tuple(names) == EXPECTED[name][0]
    assert tuple((arg.annotation.value.id, ast.literal_eval(default))
                 for arg, default in zip(fn.args.args, fn.args.defaults)) == EXPECTED_PARAMS[name]

    if name == "spatial_plant":
        returned = fn.body[-1].value
        assert fn.returns is None
        assert isinstance(returned, ast.Tuple)
        assert tuple(ast.unparse(item) for item in returned.elts) == ("geometry", "leaf_points")
    else:
        assert isinstance(fn.returns, ast.Subscript)
        assert (ast.literal_eval(fn.returns.slice),) == EXPECTED[name][1]


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_example_avoids_removed_interface_calls(name):
    """The compiler rejects legacy interface builtins throughout source modules."""
    tree = ast.parse((EXAMPLES / f"{name}.nf").read_text(encoding="utf-8"))
    assert not [node for node in ast.walk(tree)
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and (node.func.id.startswith("input_") or node.func.id == "output")]


def test_parametric_example_preserves_semantic_length_parameter():
    """Rename the source binding while retaining the L-System grammar parameter."""
    source = (EXAMPLES / "parametric_modules.nf").read_text(encoding="utf-8")
    assert "segment_length: Float['Length']" in source
    assert 'ls.param("length", segment_length)' in source
    assert 'F(length)' in source
