# NodeForge L-System

NodeForge L-System is an installable package for NodeForge that builds static and runtime L-systems as Geometry Nodes. 

## Compatibility

NodeForge L-System 4.0 supports NodeForge 0.65.0–0.65.4. Because the package contains executable Python extensions, Python permission must be enabled when it is imported.

## Public callables

The package provides semantic constructors `axiom()`, `rule()`, `iterations()`, `angle()`, `step()`, `param()`, and `marker()`. `ls.system()` consumes those package-defined semantic records and returns Geometry. `points()` extracts marker points from generated L-System geometry.

```python
from packages import lsystem as ls

geometry = ls.system(
    ls.axiom("F"),
    ls.iterations(1),
    ls.angle(25),
    ls.step(1),
)
output("Geometry", geometry)
```

## Extension architecture

`systems/lsystem/interface.py` owns the public type/callable contract, `semantic.py` owns package-domain validation and `_LSystemSpec` normalization, and `backend.py` owns physical backend selection and realization. Package helpers own L-System parsing, expansion, analysis, turtle logic, runtime tables, and concrete Geometry Nodes topology.

Generated Mesh, Curve, and Object resources are created through `ExtensionBackendContext`, so NodeForge owns rollback when compilation fails. The package does not use compiler AST/IR, `Compiler`, legacy `Value`, or v1 handler maps.

## Examples

The `examples` directory contains curve, plant, marker, parametric-module, and spatial L-System scripts.
