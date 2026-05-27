from __future__ import annotations

import urllib.request
from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface

UPSTREAM_TAG = "v0.52.0"
UPSTREAM_BASE = f"https://raw.githubusercontent.com/jupyterlab/jupyterlab-git/{UPSTREAM_TAG}/jupyterlab_git"

UPSTREAM_FILES = [
    "ssh.py",
]


class CustomBuildHook(BuildHookInterface):
    PLUGIN_NAME = "custom"

    def initialize(self, version: str, build_data: dict) -> None:
        dest_dir = Path(self.root) / "jupyterlab_git"
        for filename in UPSTREAM_FILES:
            dest = dest_dir / filename
            if not dest.exists():
                url = f"{UPSTREAM_BASE}/{filename}"
                self.app.display_info(f"[oauth-build] fetching upstream {filename} from {url}")
                urllib.request.urlretrieve(url, dest)

    def finalize(self, version: str, build_data: dict, artifact_path: str) -> None:
        dest_dir = Path(self.root) / "jupyterlab_git"
        for filename in UPSTREAM_FILES:
            dest = dest_dir / filename
            if dest.exists():
                dest.unlink()
