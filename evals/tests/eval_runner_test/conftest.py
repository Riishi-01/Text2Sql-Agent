"""Shared pytest fixtures/config for the eval_runner test suite.

Adds evals/scripts/ to sys.path so tests can `import eval_runner`,
`import rubric`, etc. directly, mirroring how the scripts import each
other at runtime.
"""
import sys
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
EVALS_DIR = TESTS_DIR.parent.parent
SCRIPTS_DIR = EVALS_DIR / "scripts"

if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
