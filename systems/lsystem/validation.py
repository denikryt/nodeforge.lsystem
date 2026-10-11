"""Validation helpers for L-system grammar strings and turtle commands."""

import re

from NodeForge.errors import CompileError
from .modules import BUILTIN_COMMANDS as COMMANDS, parse_rule_predecessor
from .interface import _Module as LSystemModule

_ALLOWED_RE = re.compile(r"^[A-Za-z0-9_]$")


def is_allowed_symbol(ch: str) -> bool:
    """Return True when *ch* is a turtle command or ignored grammar symbol."""
    return ch in COMMANDS or bool(_ALLOWED_RE.match(ch))


def validate_stream(value: str, context: str) -> str:
    """Validate an axiom or replacement string before marker-aware parsing."""
    if not isinstance(value, str):
        raise CompileError(f"{context} must be a compile-time string")
    # Parenthesized module streams are fully validated after system() collects
    # params and markers. Legacy streams keep the previous strict character contract.
    relaxed = "(" in value or ")" in value
    for ch in value:
        if relaxed and ch in "(),.":
            continue
        if ch.isspace() or not is_allowed_symbol(ch):
            raise CompileError(f"{context} contains invalid L-system symbol {ch!r}")
    return value


def validate_rule_symbol(value: str) -> str:
    """Validate a single-symbol rule predecessor."""
    return parse_rule_predecessor(value)


def validate_runtime_branch_grammar(axiom: tuple[LSystemModule, ...], rules: dict[str, tuple[LSystemModule, ...]]) -> None:
    """Validate the narrow bracket invariant required by runtime rewriting."""
    def check_balanced(modules, context):
        depth = 0
        for module in modules:
            if module.name == "[":
                depth += 1
            elif module.name == "]":
                depth -= 1
                if depth < 0:
                    raise CompileError(f"{context} contains unmatched ]")
        if depth != 0:
            raise CompileError(f"{context} contains unclosed [")

    check_balanced(axiom, "Runtime L-system axiom")
    for predecessor, replacement in rules.items():
        if predecessor in {"[", "]"}:
            raise CompileError("Runtime L-system rules cannot rewrite [ or ]")
        check_balanced(replacement, f"Runtime L-system rule {predecessor!r}")


__all__ = ["COMMANDS", "is_allowed_symbol", "validate_stream", "validate_rule_symbol", "validate_runtime_branch_grammar"]
