#!/usr/bin/env python3
from __future__ import annotations

import ast
import sys
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOMAIN_ROOTS = {
    "UOGA": Path("core/uoga"),
    "EXTRACTIVE": Path("core/extractive"),
    "HYBRID": Path("core/hybrid"),
    "SHARED": Path("core/shared"),
}
SKIP_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "venv",
    "env",
    "node_modules",
    "dist",
    "build",
    "__pycache__",
}
PROTECTED_EXECUTION_GRAPH = "Execution" + "Graph"
PROTECTED_CHUNK_PREFIX = "CHUNK" + "_"
PROTECTED_RETRY_MODULE = "retry" + "_engine"


@dataclass(frozen=True)
class ImportRef:
    module: str
    lineno: int


@dataclass(frozen=True)
class Edge:
    source: Path
    target: Path
    module: str


@dataclass(frozen=True)
class Violation:
    source: Path
    target: str
    source_domain: str
    target_domain: str
    reason: str


def repo_path(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def iter_python_files() -> list[Path]:
    files: list[Path] = []
    for path in ROOT.rglob("*.py"):
        rel_parts = path.relative_to(ROOT).parts
        if any(part in SKIP_DIRS for part in rel_parts):
            continue
        files.append(path)
    return sorted(files)


def module_name_for(path: Path) -> str:
    rel = path.relative_to(ROOT).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def domain_for(path: Path) -> str | None:
    rel = path.relative_to(ROOT)
    for domain, root in DOMAIN_ROOTS.items():
        try:
            rel.relative_to(root)
            return domain
        except ValueError:
            continue
    return None


def build_module_index(files: list[Path]) -> dict[str, Path]:
    index: dict[str, Path] = {}
    for path in files:
        module = module_name_for(path)
        if module:
            index[module] = path
    return index


def resolve_relative_module(path: Path, module: str | None, level: int) -> str | None:
    if level <= 0:
        return module
    package_parts = module_name_for(path).split(".")
    if path.name != "__init__.py":
        package_parts = package_parts[:-1]
    if level > len(package_parts) + 1:
        return module
    base = package_parts[: len(package_parts) - level + 1]
    if module:
        base.extend(module.split("."))
    return ".".join(part for part in base if part)


def import_refs(path: Path, tree: ast.AST) -> list[ImportRef]:
    refs: list[ImportRef] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                refs.append(ImportRef(alias.name, node.lineno))
        elif isinstance(node, ast.ImportFrom):
            base = resolve_relative_module(path, node.module, node.level)
            if base:
                refs.append(ImportRef(base, node.lineno))
                for alias in node.names:
                    if alias.name != "*":
                        refs.append(ImportRef(f"{base}.{alias.name}", node.lineno))
    return refs


def resolve_module(module: str, module_index: dict[str, Path]) -> Path | None:
    current = module
    while current:
        if current in module_index:
            return module_index[current]
        if "." not in current:
            break
        current = current.rsplit(".", 1)[0]
    return None


def build_graph(files: list[Path], trees: dict[Path, ast.AST]) -> tuple[set[Path], list[Edge]]:
    module_index = build_module_index(files)
    nodes = set(files)
    edges: list[Edge] = []
    for source in files:
        for ref in import_refs(source, trees[source]):
            target = resolve_module(ref.module, module_index)
            if target is not None:
                edges.append(Edge(source, target, ref.module))
    return nodes, edges


def edge_violation_reason(source_domain: str | None, target_domain: str | None) -> str | None:
    if source_domain is None or target_domain is None:
        return None
    if source_domain == "EXTRACTIVE" and target_domain == "UOGA":
        return "forbidden domain dependency edge"
    if source_domain == "HYBRID" and target_domain == "UOGA":
        return "forbidden domain dependency edge"
    if source_domain == "SHARED" and target_domain != "SHARED":
        return "shared domain may not depend on runtime domains"
    if source_domain != target_domain and target_domain != "SHARED":
        return "forbidden domain dependency edge"
    return None


def direct_edge_violations(edges: list[Edge]) -> list[Violation]:
    violations: list[Violation] = []
    for edge in edges:
        source_domain = domain_for(edge.source)
        target_domain = domain_for(edge.target)
        reason = edge_violation_reason(source_domain, target_domain)
        if reason:
            violations.append(Violation(
                edge.source,
                repo_path(edge.target),
                source_domain or "UNKNOWN",
                target_domain or "UNKNOWN",
                reason,
            ))
    return violations


def reachable_edges(nodes: set[Path], edges: list[Edge]) -> dict[Path, set[Path]]:
    adjacency: dict[Path, set[Path]] = {node: set() for node in nodes}
    for edge in edges:
        adjacency.setdefault(edge.source, set()).add(edge.target)
    reachable: dict[Path, set[Path]] = {}
    for node in nodes:
        seen: set[Path] = set()
        stack = list(adjacency.get(node, set()))
        while stack:
            current = stack.pop()
            if current in seen:
                continue
            seen.add(current)
            stack.extend(adjacency.get(current, set()) - seen)
        reachable[node] = seen
    return reachable


def transitive_violations(nodes: set[Path], edges: list[Edge]) -> list[Violation]:
    violations: list[Violation] = []
    direct_pairs = {(edge.source, edge.target) for edge in edges}
    for source, targets in reachable_edges(nodes, edges).items():
        source_domain = domain_for(source)
        if source_domain is None:
            continue
        for target in targets:
            if (source, target) in direct_pairs:
                continue
            target_domain = domain_for(target)
            reason = edge_violation_reason(source_domain, target_domain)
            if reason:
                violations.append(Violation(
                    source,
                    repo_path(target),
                    source_domain,
                    target_domain or "UNKNOWN",
                    "forbidden transitive domain dependency",
                ))
    return violations


def imports_protected_uoga_symbol(path: Path, tree: ast.AST) -> list[str]:
    offenders: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == f"core.uoga.{PROTECTED_RETRY_MODULE}":
                    offenders.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            base = resolve_relative_module(path, node.module, node.level) or ""
            for alias in node.names:
                full = f"{base}.{alias.name}" if base else alias.name
                if alias.name == PROTECTED_EXECUTION_GRAPH:
                    offenders.append(full)
                if alias.name.startswith(PROTECTED_CHUNK_PREFIX):
                    offenders.append(full)
                if full == f"core.uoga.{PROTECTED_RETRY_MODULE}":
                    offenders.append(full)
    return offenders


def fallback_protected_symbol_scan(path: Path, text: str) -> list[str]:
    offenders: list[str] = []
    if PROTECTED_EXECUTION_GRAPH in text:
        offenders.append(PROTECTED_EXECUTION_GRAPH)
    if PROTECTED_RETRY_MODULE in text and "core.uoga" in text:
        offenders.append(PROTECTED_RETRY_MODULE)
    for token in text.replace(":", " ").replace(",", " ").replace("(", " ").replace(")", " ").split():
        if token.startswith(PROTECTED_CHUNK_PREFIX):
            offenders.append(token)
    return offenders


def protected_symbol_violations(files: list[Path], trees: dict[Path, ast.AST]) -> list[Violation]:
    violations: list[Violation] = []
    for path in files:
        source_domain = domain_for(path)
        if source_domain == "UOGA":
            continue
        offenders = imports_protected_uoga_symbol(path, trees[path])
        text = path.read_text(encoding="utf-8", errors="replace")
        offenders.extend(fallback_protected_symbol_scan(path, text))
        for offender in sorted(set(offenders)):
            violations.append(Violation(
                path,
                offender,
                source_domain or "UNKNOWN",
                "UOGA",
                "protected UOGA symbol outside UOGA domain",
            ))
    return violations


def print_violation(violation: Violation) -> None:
    print(f"{repo_path(violation.source)} \u2192 {violation.target}")
    print(f"{violation.source_domain} \u2192 {violation.target_domain}")
    print(f"REASON: {violation.reason}")


def main() -> int:
    files = iter_python_files()
    trees: dict[Path, ast.AST] = {}
    violations: list[Violation] = []
    for path in files:
        try:
            trees[path] = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as exc:
            violations.append(Violation(path, str(exc), domain_for(path) or "UNKNOWN", "UNKNOWN", "syntax error"))
    valid_files = [path for path in files if path in trees]
    nodes, edges = build_graph(valid_files, trees)
    violations.extend(direct_edge_violations(edges))
    violations.extend(transitive_violations(nodes, edges))
    violations.extend(protected_symbol_violations(valid_files, trees))
    if violations:
        for index, violation in enumerate(violations):
            if index:
                print()
            print_violation(violation)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
