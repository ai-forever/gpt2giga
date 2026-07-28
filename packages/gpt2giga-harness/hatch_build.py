"""Hatch consumer hook for prebuilt, verified Cockpit assets."""

import importlib.util
from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


_CONTRACT_PATH = Path(__file__).with_name("asset_contract.py")
_SPECIFICATION = importlib.util.spec_from_file_location(
    "_gpt2giga_harness_asset_contract",
    _CONTRACT_PATH,
)
if _SPECIFICATION is None or _SPECIFICATION.loader is None:
    raise RuntimeError(f"Unable to load Cockpit asset contract: {_CONTRACT_PATH}")
_CONTRACT = importlib.util.module_from_spec(_SPECIFICATION)
_SPECIFICATION.loader.exec_module(_CONTRACT)


class CustomBuildHook(BuildHookInterface):
    """Fail closed before Hatch can package missing or stale Cockpit assets."""

    PLUGIN_NAME = "custom"

    def initialize(self, version, build_data):
        """Validate the injected tree without invoking Node or the network."""
        _CONTRACT.verify_asset_tree(self.root)
        pattern = f"{_CONTRACT.ASSET_RELATIVE_ROOT.as_posix()}/**"
        if pattern not in build_data["artifacts"]:
            build_data["artifacts"].append(pattern)
