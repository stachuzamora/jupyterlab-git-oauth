import sys
from unittest.mock import MagicMock

# These files exist in upstream jupyterlab-git but not in this repo.
# Mock them so our patches in git.py / handlers.py can be imported and tested.
sys.modules.setdefault("jupyterlab_git.ssh", MagicMock())

_version_mock = MagicMock()
_version_mock.__version__ = "0.52.0"
sys.modules.setdefault("jupyterlab_git._version", _version_mock)
