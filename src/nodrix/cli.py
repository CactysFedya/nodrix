"""Stable Nodrix CLI facade.

Commands are registered by focused modules while ``nodrix.cli:app`` remains
the unchanged console entry point.
"""

from .cli_context import app
from . import cli_admin_commands  # noqa: F401  # command registration
from . import cli_catalog_commands  # noqa: F401  # command registration
from . import cli_operation_commands  # noqa: F401  # command registration
from . import cli_project_commands  # noqa: F401  # command registration


def main() -> None:
    app()


if __name__ == "__main__":
    main()
