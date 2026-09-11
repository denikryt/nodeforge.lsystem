from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = PACKAGE_ROOT.parent
ADDON_ROOT = PROJECT_ROOT / "NodeForge"
BLENDER_TESTS = ADDON_ROOT / "tests" / "blender"
for path in (PROJECT_ROOT, ADDON_ROOT, BLENDER_TESTS):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from NodeForge import packages


@pytest.fixture(scope="session", autouse=True)
def installed_lsystem_package():
    with tempfile.TemporaryDirectory() as tmp:
        packages.set_packages_dir_for_tests(Path(tmp) / "packages")
        packages.install_package_directory(PACKAGE_ROOT, allow_python=True)
        try:
            yield
        finally:
            try:
                packages.uninstall_package("nodeforge.lsystem")
            except Exception:
                pass
            packages.set_packages_dir_for_tests(None)
            packages.invalidate_caches()
