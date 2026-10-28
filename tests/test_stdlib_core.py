"""The stdlib core runs where its vendored copies run: Python 3.9 (the host's /usr/bin/python3), without any package."""

import ast
import subprocess
import sys
from pathlib import Path

import pytest

PACKAGE = Path(__file__).parent.parent / "src" / "agentkit"
# The modules a vendored copy may take one by one: stdlib only, no import of each other.
CORE = ("redact", "safefs", "fetch", "sqlite")
OLD_PYTHON = Path("/usr/bin/python3")


@pytest.mark.parametrize("name", CORE)
def test_a_core_module_imports_only_the_stdlib(name):
    tree = ast.parse((PACKAGE / f"{name}.py").read_text())
    imported = {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import)
                for alias in node.names}
    imported |= {node.module.split(".")[0] for node in ast.walk(tree)
                 if isinstance(node, ast.ImportFrom) and node.module and node.level == 0}
    assert imported <= set(sys.stdlib_module_names) | {"__future__"}, imported


def test_the_core_runs_on_python_3_9():
    if not OLD_PYTHON.exists():
        pytest.skip("no /usr/bin/python3 here")
    # As a vendored copy is laid out: the package folder on sys.path, each module imported by its full name.
    smoke = ("import sys, tempfile, os; sys.path.insert(0, sys.argv[1]); "
             "from agentkit import redact, safefs, fetch, sqlite; "
             "assert fetch.is_public('8.8.8.8'); "
             "assert redact.scrub_text('Bearer abcDEF0123456789xyz', ()) == 'Bearer ' + redact.MASK; "
             "d = tempfile.mkdtemp(); safefs.write_atomic(os.path.join(d, 'f'), b'x'); "
             "fd = safefs.walk(d); f, _ = safefs.open_regular(fd, 'f'); assert safefs.read_bounded(f, 1) == b'x'")
    done = subprocess.run([str(OLD_PYTHON), "-I", "-c", smoke, str(PACKAGE.parent)], capture_output=True, text=True,
                          timeout=60)
    assert done.returncode == 0, done.stderr
