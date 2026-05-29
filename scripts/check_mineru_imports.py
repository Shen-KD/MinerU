#!/usr/bin/env python3
"""Static import checker for in-repo mineru modules (no third-party install)."""
from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MINERU = ROOT / "mineru"


def module_path(mod: str) -> Path | None:
    rel = mod.replace("mineru.", "").replace(".", "/")
    py = MINERU / f"{rel}.py"
    if py.exists():
        return py
    pkg = MINERU / rel / "__init__.py"
    if pkg.exists():
        return pkg
    return None


def exported_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.asname or alias.name.split(".")[-1])
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name != "*":
                    names.add(alias.asname or alias.name)
    return names


def collect_imports(path: Path) -> list[tuple[str, str, int]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    out: list[tuple[str, str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("mineru"):
            for alias in node.names:
                if alias.name == "*":
                    continue
                out.append((node.module, alias.asname or alias.name, node.lineno))
    return out


def main() -> int:
    errors: list[str] = []
    for py in sorted(MINERU.rglob("*.py")):
        for mod, name, lineno in collect_imports(py):
            target = module_path(mod)
            rel = py.relative_to(ROOT)
            if target is None:
                errors.append(f"{rel}:{lineno}: module missing: {mod}")
                continue
            if name not in exported_names(target):
                errors.append(f"{rel}:{lineno}: {mod}.{name} not found in {target.relative_to(ROOT)}")

    entrypoints = [
        "mineru.cli.fast_api",
        "mineru.cli.router",
        "mineru.cli.common",
        "mineru.cli.gradio_app",
        "mineru.cli.vlm_server",
    ]
    for ep in entrypoints:
        p = module_path(ep)
        if p is None:
            errors.append(f"entrypoint missing module: {ep}")

    if errors:
        print("IMPORT CHECK FAILED:")
        for e in errors:
            print(" ", e)
        return 1

    print(f"IMPORT CHECK OK ({len(list(MINERU.rglob('*.py')))} files scanned)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
