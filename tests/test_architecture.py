"""Enforces AGENTS.md invariants 1, 2 and 21: one-way imports, façade-only cross-module imports,
re-export-only __init__ files, docstring headers on every module file, and an `app.py` that only
constructs sessions and calls `setup` / `start` / `stop`."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "sidekick"
EXTENSIONS = ROOT / "extensions"

# The allowed-import table from AGENTS.md "Architecture". `app` and `cli` may import anything.
ALLOWED: dict[str, set[str]] = {
    "audio": set(),
    "log": set(),
    "storage": {"log"},
    "llm": {"log", "storage"},
    "asr": {"log", "storage", "audio"},
    "tts": {"log", "storage", "audio"},
    "vad": {"log", "storage", "audio"},
    "body": {"log", "audio"},
    "config": {"log", "storage", "audio", "llm", "asr", "tts", "vad"},
    "channel": {"log", "storage"},
    "contact": {"log", "storage", "audio"},
    "perception": {"log", "storage", "audio", "body", "contact"},
    "interaction": {
        "log",
        "storage",
        "audio",
        "body",
        "asr",
        "tts",
        "vad",
        "channel",
        "contact",
        "perception",
    },
    "agent": {"log", "storage", "llm", "channel", "contact", "perception"},
    "automation": {"log", "storage", "agent", "perception"},
    "extension": {"log", "storage", "agent", "automation", "perception"},
    "record": {"log", "storage", "audio", "body"},
    "service": {"log", "storage", "config"},
    "extensions": {
        "log",
        "storage",
        "audio",
        "llm",
        "body",
        "contact",
        "perception",
        "interaction",
        "agent",
        "extension",
    },
}
ANY = {"dashboard", "doctor", "app", "cli"}


def module_of(path: Path) -> str:
    if path.is_relative_to(SRC):
        rel = path.relative_to(SRC)
        return rel.parts[0] if len(rel.parts) > 1 else rel.stem
    return "extensions"


def sidekick_files() -> list[Path]:
    files = list(SRC.rglob("*.py"))
    if EXTENSIONS.exists():
        files += list(EXTENSIONS.rglob("*.py"))
    return sorted(files)


def imports_of(path: Path) -> list[tuple[str, int]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.append((alias.name, 0))
        elif isinstance(node, ast.ImportFrom):
            found.append((node.module or "", node.level))
    return found


def test_no_nested_directories_inside_modules():
    for module_dir in SRC.iterdir():
        if module_dir.is_dir() and module_dir.name != "__pycache__":
            nested = [p for p in module_dir.iterdir() if p.is_dir() and p.name != "__pycache__"]
            assert not nested, f"{module_dir.name} has nested directories: {nested}"


def test_cross_module_imports_follow_the_table_and_use_facades():
    violations = []
    for path in sidekick_files():
        module = module_of(path)
        for name, level in imports_of(path):
            if level > 0 or not name.startswith("sidekick"):
                continue
            parts = name.split(".")
            if len(parts) == 1:
                continue  # `from sidekick import __version__`
            target = parts[1]
            if target == module:
                violations.append(
                    f"{path.relative_to(ROOT)}: use relative imports inside the module, not {name}"
                )
                continue
            if len(parts) > 2:
                violations.append(
                    f"{path.relative_to(ROOT)}: deep import {name}; import from sidekick.{target}"
                )
            if module in ANY:
                continue
            if target not in ALLOWED.get(module, set()):
                violations.append(
                    f"{path.relative_to(ROOT)}: {module} may not import sidekick.{target}"
                )
    assert not violations, "\n".join(violations)


def test_submodules_never_import_the_facade():
    violations = []
    for path in sidekick_files():
        module = module_of(path)
        if path.name in ("__init__.py", f"{module}.py") or module in ANY:
            continue
        for name, level in imports_of(path):
            if level == 1 and name == module:
                violations.append(f"{path.relative_to(ROOT)} imports the façade .{module}")
    assert not violations, "\n".join(violations)


def test_init_files_only_reexport():
    violations = []
    for path in sidekick_files():
        if path.name != "__init__.py" or path.parent == SRC:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            ok = isinstance(node, ast.ImportFrom) and node.level == 1
            ok = ok or (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant))
            ok = ok or (
                isinstance(node, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets)
            )
            if not ok:
                violations.append(
                    f"{path.relative_to(ROOT)}: {type(node).__name__} at line {node.lineno}"
                )
    assert not violations, "\n".join(violations)


def test_every_module_file_has_a_design_header():
    missing = []
    for path in sidekick_files():
        if path.name == "__init__.py":
            continue
        doc = ast.get_docstring(ast.parse(path.read_text(encoding="utf-8")))
        if not doc or "Overview" not in doc or "Design" not in doc:
            missing.append(str(path.relative_to(ROOT)))
    assert not missing, "files without an Overview/Design header:\n" + "\n".join(missing)


def test_facade_exists_for_every_module_directory():
    for module_dir in SRC.iterdir():
        if module_dir.is_dir() and module_dir.name != "__pycache__":
            assert (module_dir / f"{module_dir.name}.py").exists(), (
                f"{module_dir.name} lacks its façade"
            )
            assert (module_dir / "__init__.py").exists()


COMPOSITION_METHODS = ("construct", "setup_service", "start", "stop")
LIFECYCLE = {"setup", "start", "stop"}
NOT_COMPOSITION = (
    ast.If,
    ast.IfExp,
    ast.For,
    ast.AsyncFor,
    ast.While,
    ast.Try,
    ast.With,
    ast.AsyncWith,
    ast.Match,
    ast.Lambda,
    ast.FunctionDef,
    ast.AsyncFunctionDef,
    ast.ClassDef,
)


def _is_lifecycle_call(call: ast.Call) -> bool:
    func = call.func
    if isinstance(func, ast.Attribute) and func.attr in LIFECYCLE:
        return True
    if isinstance(func, ast.Attribute) and func.attr in ("info0", "info"):
        return ast.unparse(func.value) == "Log"
    return (
        ast.unparse(func) == "asyncio.to_thread"
        and bool(call.args)
        and isinstance(call.args[0], ast.Attribute)
        and call.args[0].attr in LIFECYCLE
    )


def _assignable(target: ast.expr) -> bool:
    if isinstance(target, ast.Name):
        return True
    return isinstance(target, ast.Attribute) and (
        target.attr == "shared"
        or (isinstance(target.value, ast.Name) and target.value.id == "self")
    )


def test_app_only_composes():
    """Invariant 21: no control flow, closures or wiring of its own in `App` composition."""
    tree = ast.parse((SRC / "app.py").read_text(encoding="utf-8"))
    app = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "App")
    methods = [
        m
        for m in app.body
        if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)) and m.name in COMPOSITION_METHODS
    ]
    assert {m.name for m in methods} == set(COMPOSITION_METHODS)
    violations = []
    for method in methods:
        where = f"App.{method.name}"
        for node in ast.walk(method):
            if node is not method and isinstance(node, NOT_COMPOSITION):
                violations.append(f"{where} line {node.lineno}: {type(node).__name__}")
        for stmt in method.body:
            if isinstance(stmt, ast.Assert) or (
                isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant)
            ):
                continue
            if isinstance(stmt, (ast.Assign, ast.AnnAssign)):
                targets = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]
                violations += [
                    f"{where} line {stmt.lineno}: assigns {ast.unparse(t)}"
                    for t in targets
                    if not _assignable(t)
                ]
                continue
            if isinstance(stmt, ast.Expr):
                call = stmt.value.value if isinstance(stmt.value, ast.Await) else stmt.value
                if isinstance(call, ast.Call) and _is_lifecycle_call(call):
                    continue
            violations.append(f"{where} line {stmt.lineno}: {ast.unparse(stmt)[:70]}")
    assert not violations, "app.py does more than compose:\n" + "\n".join(violations)


def test_the_dashboard_never_spawns_or_signals_a_process():
    """Invariant 25: the process is the CLI's; the dashboard (and readiness) only switch the
    service inside it, so neither may import `subprocess`, `signal` or call `os.kill`."""
    violations = []
    for module in ("dashboard", "doctor", "service"):
        for path in sorted((SRC / module).glob("*.py")):
            text = path.read_text(encoding="utf-8")
            for name, _level in imports_of(path):
                if name.split(".")[0] in ("subprocess", "signal"):
                    violations.append(f"{path.relative_to(ROOT)} imports {name}")
            if "os.kill(" in text:
                violations.append(f"{path.relative_to(ROOT)} calls os.kill")
    assert not violations, "\n".join(violations)
