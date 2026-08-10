"""Stable Plyctl CLI facade.

Commands are registered by focused modules. ``nodrix.cli:app`` remains a
supported compatibility entry point throughout the 2.x series.
"""

from .cli_context import app
from . import cli_admin_commands  # noqa: F401  # command registration
from . import cli_agent_commands  # noqa: F401  # 2.8 remote agent registration
from . import cli_catalog_commands  # noqa: F401  # command registration
from . import cli_operation_commands  # noqa: F401  # command registration
from . import cli_project_commands  # noqa: F401  # command registration
from . import cli_dev_commands  # noqa: F401  # command registration
from . import cli_foundation_commands  # noqa: F401  # command registration
from . import cli_workspace_commands  # noqa: F401  # command registration
from . import cli_system_commands  # noqa: F401  # command registration
from . import cli_system_run_orchestration  # noqa: F401  # 2.8 run override


def main() -> None:
    app()


if __name__ == "__main__":
    main()
