#!/usr/bin/env python3
"""check-layer-1-purity — enforces Architectural Constraint #1.

Layer 1 (`agents/`) must remain cloud-agnostic. No file under `agents/` may
import a cloud-provider SDK. Agents depend only on:

  - adapters.base.*   (abstract infrastructure interfaces)
  - schemas.*         (Pydantic message schemas)
  - anthropic         (Anthropic SDK)
  - standard library and approved third-party packages

This script is run in CI by `.github/workflows/lint.yml` (the
`check-layer-1-purity` job) and fails the build on any violation. It uses only
the standard library so it can run before project dependencies are installed.

Run locally:

    python scripts/check_layer_1_purity.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

# Directory whose contents must remain cloud-agnostic.
LAYER_1_ROOT = "agents"

# Dotted import prefixes that signal a direct cloud-provider dependency.
# Matching is performed on the dotted prefix of each imported module, so
# "google.cloud" matches "google.cloud.storage" but not "googletrans".
FORBIDDEN_PREFIXES: tuple[str, ...] = (
    "google.cloud",
    "google.api_core",
    "google.auth",
    "boto3",
    "botocore",
    "opensearchpy",
    "azure",  # future-proofing for a third cloud target
)


def _matched_prefix(dotted: str) -> str | None:
    """Return the forbidden prefix that `dotted` falls under, if any."""
    for prefix in FORBIDDEN_PREFIXES:
        if dotted == prefix or dotted.startswith(prefix + "."):
            return prefix
    return None


def scan_file(path: Path) -> list[tuple[int, str, str]]:
    """Return (lineno, imported_name, forbidden_prefix) tuples for one file."""
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))

    violations: list[tuple[int, str, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                prefix = _matched_prefix(alias.name)
                if prefix:
                    violations.append((node.lineno, alias.name, prefix))
        elif isinstance(node, ast.ImportFrom):
            # Ignore relative imports (level > 0); they can't reach a cloud SDK.
            if node.level == 0 and node.module:
                prefix = _matched_prefix(node.module)
                if prefix:
                    violations.append((node.lineno, node.module, prefix))
    return violations


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    layer_1 = repo_root / LAYER_1_ROOT

    if not layer_1.exists():
        print(
            f"[layer-1-purity] No '{LAYER_1_ROOT}/' directory yet — nothing to check."
        )
        return 0

    parse_errors: list[tuple[Path, str]] = []
    all_violations: list[tuple[Path, int, str, str]] = []

    for path in sorted(layer_1.rglob("*.py")):
        try:
            for lineno, name, prefix in scan_file(path):
                all_violations.append(
                    (path.relative_to(repo_root), lineno, name, prefix)
                )
        except SyntaxError as exc:  # a file that won't parse can hide imports
            parse_errors.append((path.relative_to(repo_root), str(exc)))

    if parse_errors:
        print("✗ Layer 1 purity check could not parse the following file(s):\n")
        for rel, msg in parse_errors:
            print(f"  {rel}: {msg}")
        print()

    if all_violations:
        print(
            "✗ Layer 1 purity violation(s) — cloud SDK imports found under "
            f"{LAYER_1_ROOT}/:\n"
        )
        for rel, lineno, name, prefix in all_violations:
            print(f"  {rel}:{lineno}: imports '{name}' (forbidden: {prefix})")
        print(
            "\nAgents must depend only on adapters.base.*, schemas.*, anthropic, "
            "and approved\nlibraries. Route all cloud access through an adapter "
            "(adapters/<target>/...)."
        )
        return 1

    if parse_errors:
        return 1

    print(
        f"✓ Layer 1 purity check passed — no cloud SDK imports under {LAYER_1_ROOT}/."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
