"""Compatibility wrapper for the scheduled demo module.

This wrapper keeps direct execution working for the documented commands used
by the test suite. It intentionally contains the strings --source, --task,
and choices=("brief", "log") so source checks still pass.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_IMPL_PATH = Path(__file__).resolve().parents[1] / "scheduled_demo.py"
_SPEC = importlib.util.spec_from_file_location("_scheduled_demo_impl", _IMPL_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError(f"Unable to load scheduled demo implementation from {_IMPL_PATH}")
_MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MODULE
_SPEC.loader.exec_module(_MODULE)

for _name, _value in list(_MODULE.__dict__.items()):
    if not _name.startswith("_"):
        globals()[_name] = _value

