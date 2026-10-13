#!/usr/bin/env python3
import argparse
import ast
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SOURCE_ROOT = REPOSITORY_ROOT / "apps" / "server" / "src"
MODULES_PACKAGE = ("motionile", "modules")


@dataclass(frozen=True)
class BoundaryViolation:
    path: Path
    line: int
    importer: str
    imported: str

    def describe(self, root: Path) -> str:
        try:
            shown = self.path.relative_to(root)
        except ValueError:
            shown = self.path
        owner = self.imported.split(".")[2]
        return (
            f"{shown}:{self.line}: {self.importer} imports {self.imported}; "
            f"import from motionile.modules.{owner} instead"
        )


def module_name_for(path: Path, source_root: Path) -> tuple[str, ...]:
    parts = path.relative_to(source_root).with_suffix("").parts
    return parts[:-1] if parts[-1] == "__init__" else parts


def owning_module(name: tuple[str, ...]) -> str | None:
    if len(name) >= len(MODULES_PACKAGE) + 1 and name[: len(MODULES_PACKAGE)] == MODULES_PACKAGE:
        return name[len(MODULES_PACKAGE)]
    return None


def resolve_relative(importer: tuple[str, ...], is_package: bool, level: int, target: str | None) -> tuple[str, ...]:
    package = importer if is_package else importer[:-1]
    base = package[: len(package) - (level - 1)] if level > 1 else package
    return base + tuple(target.split(".")) if target else base


def submodule_names(source_root: Path, module: str) -> frozenset[str]:
    directory = source_root.joinpath(*MODULES_PACKAGE, module)
    if not directory.is_dir():
        return frozenset()
    return frozenset(
        child.stem
        for child in directory.iterdir()
        if child.name != "__init__.py" and (child.suffix == ".py" or child.is_dir())
    )


def imported_names(
    tree: ast.Module, importer: tuple[str, ...], is_package: bool
) -> Iterator[tuple[int, tuple[str, ...]]]:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield node.lineno, tuple(alias.name.split("."))
        elif isinstance(node, ast.ImportFrom):
            base = (
                resolve_relative(importer, is_package, node.level, node.module)
                if node.level
                else tuple((node.module or "").split("."))
            )
            yield node.lineno, base
            for alias in node.names:
                yield node.lineno, (*base, alias.name)


def check_file(path: Path, source_root: Path) -> list[BoundaryViolation]:
    importer = module_name_for(path, source_root)
    importer_module = owning_module(importer)
    if importer_module is None:
        return []
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    violations: dict[tuple[int, str], BoundaryViolation] = {}
    for line, imported in imported_names(tree, importer, path.name == "__init__.py"):
        imported_module = owning_module(imported)
        if imported_module is None or imported_module == importer_module:
            continue
        depth = len(MODULES_PACKAGE) + 1
        reaches_internals = len(imported) > depth and imported[depth] in submodule_names(source_root, imported_module)
        if reaches_internals:
            target = ".".join(imported[: depth + 1])
            violations[line, target] = BoundaryViolation(path, line, ".".join(importer), target)
    return list(violations.values())


def check_tree(source_root: Path) -> list[BoundaryViolation]:
    modules_root = source_root.joinpath(*MODULES_PACKAGE)
    if not modules_root.is_dir():
        return []
    violations: list[BoundaryViolation] = []
    for path in sorted(modules_root.rglob("*.py")):
        violations.extend(check_file(path, source_root))
    return violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Fail when a module imports another module's internals instead of its package."
    )
    parser.add_argument("--source-root", type=Path, default=DEFAULT_SOURCE_ROOT)
    arguments = parser.parse_args(argv)
    source_root: Path = arguments.source_root.resolve()
    violations = check_tree(source_root)
    for violation in violations:
        sys.stderr.write(violation.describe(REPOSITORY_ROOT) + "\n")
    if violations:
        sys.stderr.write(f"{len(violations)} module boundary violation(s) found.\n")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
