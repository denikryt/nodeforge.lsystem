# NodeForge L-System

NodeForge L-System is an installable package for NodeForge that builds static and runtime L-systems as Geometry Nodes. Version 2.3 uses NodeForge Extension API v2 end to end.

## Compatibility

NodeForge L-System 2.3 supports NodeForge 0.62.0 through 0.62.2. Because the package contains executable Python extensions, Python permission must be enabled when it is imported.

## Public callables

The package provides semantic constructors `ls_axiom()`, `ls_rule()`, `ls_iterations()`, `ls_angle()`, `ls_step()`, `ls_param()`, and `ls_marker()`. `ls_system()` consumes those package-defined semantic records and returns Geometry. `ls_points()` extracts marker points from generated L-System geometry.

Constructor values can be assigned to source variables before being passed to `ls_system()`. Runtime numeric dependencies inside those records use NodeForge's generic persistent extension-value mechanism.

## Extension architecture

`systems/lsystem/interface.py` owns the public type/callable contract, `semantic.py` owns package-domain validation and `_LSystemSpec` normalization, and `backend.py` owns physical backend selection and realization. Package helpers own L-System parsing, expansion, analysis, turtle logic, runtime tables, and concrete Geometry Nodes topology.

Generated Mesh, Curve, and Object resources are created through `ExtensionBackendContext`, so NodeForge owns rollback when compilation fails. The package does not use compiler AST/IR, `Compiler`, legacy `Value`, or v1 handler maps.

## Examples

The `examples` directory contains curve, plant, marker, parametric-module, and spatial L-System scripts.
