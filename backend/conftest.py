"""Root conftest: put backend/ (this file's dir) on sys.path so `import app`
resolves under any pytest invocation and version.

pytest's `pythonpath` ini option would do this too, but only on pytest >= 7;
the local toolchain has 6.2.4, so this guarantees it everywhere. Loaded before
tests/conftest.py (rootdir down), so `app` is importable by the time it runs.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
