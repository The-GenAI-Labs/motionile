#!/usr/bin/env python3
import argparse
import io
import re
import subprocess
import sys
import tokenize
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent

PYTHON_DIRECTIVES = (
    re.compile(r"^noqa: [A-Z]+[0-9]+(, ?[A-Z]+[0-9]+)*$"),
    re.compile(r"^type: ignore\[[\w-]+(, ?[\w-]+)*\]$"),
    re.compile(r"^pragma: no cover$"),
)

EXCLUDED_PARTS = frozenset({"node_modules", ".venv", ".next", ".turbo", ".terraform", "fixtures", "generated"})
EXCLUDED_NAMES = frozenset({"uv.lock", "pnpm-lock.yaml", ".terraform.lock.hcl"})
HEREDOC_START = re.compile(r"<<-?([A-Za-z_][A-Za-z0-9_]*)\s*$")
TEMPLATE_DIRECTIVES = frozenset({"#cloud-config"})
INLINE_HASH_COMMENT_NAMES = frozenset({"Dockerfile", "Caddyfile", ".env.example", ".env.development"})
INLINE_HASH_COMMENT_SUFFIXES = frozenset({".yml", ".yaml", ".toml", ".sh", ".bash", ".Dockerfile"})
LINE_START_COMMENT_NAMES = frozenset(
    {".gitignore", ".dockerignore", ".prettierignore", ".gitattributes", ".npmrc", ".editorconfig"}
)
LINE_START_COMMENT_SUFFIXES = frozenset({".tsv"})


@dataclass(frozen=True)
class Violation:
    path: Path
    line: int
    text: str

    def describe(self, root: Path) -> str:
        try:
            shown = self.path.relative_to(root)
        except ValueError:
            shown = self.path
        return f"{shown}:{self.line}: comment not allowed: {self.text.strip()}"


def is_python_directive(comment: str) -> bool:
    segments = [segment.strip() for segment in comment.split("#") if segment.strip()]
    return bool(segments) and all(any(pattern.match(segment) for pattern in PYTHON_DIRECTIVES) for segment in segments)


def python_comments(source: str) -> Iterator[tuple[int, str]]:
    tokens = tokenize.generate_tokens(io.StringIO(source).readline)
    for token in tokens:
        if token.type != tokenize.COMMENT:
            continue
        line, column = token.start
        if line == 1 and column == 0 and token.string.startswith("#!"):
            continue
        if not is_python_directive(token.string):
            yield line, token.string


def hash_comment_start(line: str, *, line_start_only: bool) -> int | None:
    stripped = line.lstrip()
    if stripped.startswith("#"):
        return len(line) - len(stripped)
    if line_start_only:
        return None
    quote: str | None = None
    escaped = False
    for index, character in enumerate(line):
        if escaped:
            escaped = False
            continue
        if character == "\\" and quote != "'":
            escaped = True
            continue
        if quote is not None:
            if character == quote:
                quote = None
            continue
        if character in "\"'`":
            quote = character
            continue
        if character == "#" and line[index - 1] in " \t":
            return index
    return None


def hash_comments(source: str, *, line_start_only: bool) -> Iterator[tuple[int, str]]:
    for number, line in enumerate(source.splitlines(), start=1):
        if number == 1 and line.startswith("#!"):
            continue
        start = hash_comment_start(line, line_start_only=line_start_only)
        if start is not None:
            yield number, line[start:]


def block_comments(source: str, *, line_markers: tuple[str, ...] = ()) -> Iterator[tuple[int, str]]:
    quote: str | None = None
    index = 0
    line = 1
    while index < len(source):
        character = source[index]
        if character == "\n":
            line += 1
        if quote is not None:
            if character == "\\":
                index += 2
                continue
            if character == quote:
                quote = None
            index += 1
            continue
        if character in "\"'":
            quote = character
            index += 1
            continue
        if source.startswith("/*", index):
            end = source.find("*/", index + 2)
            end = len(source) if end == -1 else end + 2
            yield line, source[index:end]
            line += source.count("\n", index, end)
            index = end
            continue
        marker = next((candidate for candidate in line_markers if source.startswith(candidate, index)), None)
        if marker is not None:
            end = source.find("\n", index)
            end = len(source) if end == -1 else end
            yield line, source[index:end]
            index = end
            continue
        index += 1


def css_comments(source: str) -> Iterator[tuple[int, str]]:
    return block_comments(source)


def sql_comments(source: str) -> Iterator[tuple[int, str]]:
    return block_comments(source, line_markers=("--",))


def hcl_line_comments(line: str, number: int, state: list[str]) -> Iterator[tuple[int, str]]:
    index = 0
    while index < len(line):
        character = line[index]
        context = state[-1] if state else "code"
        if context == "block":
            end = line.find("*/", index)
            if end == -1:
                return
            state.pop()
            index = end + 2
            continue
        if context == "string":
            if character == "\\":
                index += 2
                continue
            if line.startswith("${", index) or line.startswith("%{", index):
                state.append("interpolation")
                index += 2
                continue
            if character == '"':
                state.pop()
            index += 1
            continue
        if character == '"':
            state.append("string")
        elif character == "{" and context == "interpolation":
            state.append("interpolation")
        elif character == "}" and context == "interpolation":
            state.pop()
        elif character == "#" or line.startswith("//", index):
            yield number, line[index:]
            return
        elif line.startswith("/*", index):
            yield number, line[index:]
            state.append("block")
            index += 2
            continue
        index += 1


def hcl_comments(source: str) -> Iterator[tuple[int, str]]:
    state: list[str] = []
    heredoc_end: str | None = None
    for number, line in enumerate(source.splitlines(), start=1):
        if heredoc_end is not None:
            if line.strip() == heredoc_end:
                heredoc_end = None
            continue
        yield from hcl_line_comments(line, number, state)
        heredoc = HEREDOC_START.search(line)
        if heredoc is not None and not state:
            heredoc_end = heredoc.group(1)


def template_comments(source: str) -> Iterator[tuple[int, str]]:
    for number, line in enumerate(source.splitlines(), start=1):
        stripped = line.strip()
        if (number == 1 and stripped in TEMPLATE_DIRECTIVES) or stripped.startswith("#!/"):
            continue
        if stripped.startswith(("//", "/*", "%{/*")):
            yield number, stripped
            continue
        start = hash_comment_start(line, line_start_only=False)
        if start is not None:
            yield number, line[start:]


def lua_comments(source: str) -> Iterator[tuple[int, str]]:
    return block_comments(source, line_markers=("--",))


type Scanner = Callable[[str], Iterable[tuple[int, str]]]


SCANNERS_BY_SUFFIX: dict[str, Scanner] = {
    ".py": python_comments,
    ".css": css_comments,
    ".sql": sql_comments,
    ".lua": lua_comments,
    ".tf": hcl_comments,
    ".hcl": hcl_comments,
    ".tftpl": template_comments,
}


def scanner_for(path: Path) -> Scanner | None:
    name = path.name
    by_suffix = SCANNERS_BY_SUFFIX.get(path.suffix)
    if by_suffix is not None:
        return by_suffix
    if name in LINE_START_COMMENT_NAMES or path.suffix in LINE_START_COMMENT_SUFFIXES:
        return lambda source: hash_comments(source, line_start_only=True)
    if name in INLINE_HASH_COMMENT_NAMES or path.suffix in INLINE_HASH_COMMENT_SUFFIXES or path.parent.name == ".husky":
        return lambda source: hash_comments(source, line_start_only=False)
    return None


def is_excluded(path: Path) -> bool:
    return path.name in EXCLUDED_NAMES or bool(EXCLUDED_PARTS.intersection(path.parts))


def check_file(path: Path) -> list[Violation]:
    scanner = scanner_for(path)
    if scanner is None:
        return []
    source = path.read_text(encoding="utf-8")
    return [Violation(path, line, text) for line, text in scanner(source)]


def repository_files(root: Path) -> list[Path]:
    listing = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],  # noqa: S607
        cwd=root,
        check=True,
        capture_output=True,
    )
    names = [name for name in listing.stdout.decode().split("\0") if name]
    return [root / name for name in names if (root / name).is_file()]


def collect_violations(paths: Iterable[Path]) -> list[Violation]:
    violations: list[Violation] = []
    for path in paths:
        if not is_excluded(path):
            violations.extend(check_file(path))
    return violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fail when authored files contain comments.")
    parser.add_argument("paths", nargs="*", type=Path, help="Files to check. Defaults to the whole repository.")
    arguments = parser.parse_args(argv)
    paths: list[Path] = [path.resolve() for path in arguments.paths] or repository_files(REPOSITORY_ROOT)
    violations = collect_violations(paths)
    for violation in violations:
        sys.stderr.write(violation.describe(REPOSITORY_ROOT) + "\n")
    if violations:
        sys.stderr.write(f"{len(violations)} comment(s) found. Express intent through names and structure.\n")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
