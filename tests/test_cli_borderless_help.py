from typer.testing import CliRunner

from nodrix.cli import app


runner = CliRunner()


BORDER_CHARS = (
    "┏┓┗┛┃"
    "╭╮╰╯"
    "┌┐└┘│"
    "━"
    "┡┩"
)


def assert_borderless(output: str) -> None:
    assert not any(
        char in output
        for char in BORDER_CHARS
    )


def test_root_help_is_borderless() -> None:
    result = runner.invoke(
        app,
        ["--help"],
    )

    assert result.exit_code == 0
    assert_borderless(result.stdout)


def test_runs_help_is_borderless() -> None:
    result = runner.invoke(
        app,
        [
            "runs",
            "--help",
        ],
    )

    assert result.exit_code == 0
    assert_borderless(result.stdout)


def test_runs_show_help_is_borderless() -> None:
    result = runner.invoke(
        app,
        [
            "runs",
            "show",
            "--help",
        ],
    )

    assert result.exit_code == 0
    assert_borderless(result.stdout)
