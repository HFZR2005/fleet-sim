"""Command line for fleet-sim."""

import contextvars
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Annotated

import typer
from typer._click.exceptions import ClickException  # Typer vendors Click

from fleet_sim.commands import run_home
from fleet_sim.models.prices import ClockChangeDayError
from fleet_sim.render import show_run_home

_OPENER: contextvars.ContextVar[Callable[[str], bytes] | None] = contextvars.ContextVar(
    "fleet_sim_price_opener",
    default=None,
)

app = typer.Typer(
    name="fleet-sim", no_args_is_help=True, pretty_exceptions_enable=False
)
_DEFAULT_OUTPUT = Path("figures") / "day"


@app.callback()
def app_callback() -> None:
    """Schedule home batteries against half-hourly electricity prices."""


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise typer.BadParameter(f"date must be YYYY-MM-DD (got {value})") from exc


def main(
    argv: list[str] | None = None,
    opener: Callable[[str], bytes] | None = None,
) -> int:
    """Run the fleet-sim command in ``argv``.

    ``opener`` is the price-fetch stand-in used by tests. The installed
    command leaves it unset and fetches from Octopus.
    """
    token = _OPENER.set(opener)
    try:
        result = typer.main.get_command(app).main(
            args=argv,
            prog_name="fleet-sim",
            standalone_mode=False,
        )
    except ClickException as exc:
        exc.show()
        return exc.exit_code
    finally:
        _OPENER.reset(token)
    if isinstance(result, int):
        return result
    return 0


@app.command("run-home")
def run_home_command(
    day: Annotated[
        date,
        typer.Option(
            "--date",
            parser=_parse_date,
            metavar="YYYY-MM-DD",
            help="UK civil day",
        ),
    ],
    region: Annotated[str, typer.Option(help="Octopus GSP letter, for example C")],
    config: Annotated[Path, typer.Option(help="Home config")] = Path("home.toml"),
    output: Annotated[Path, typer.Option(help="Figure path without suffix")] = (
        _DEFAULT_OUTPUT
    ),
    cache_dir: Annotated[
        Path | None,
        typer.Option(
            help="Price cache directory (default: .cache/agile)",
            show_default=False,
        ),
    ] = None,
) -> None:
    """Fetch one day of Agile prices and schedule one home."""
    try:
        report, n = run_home(
            day,
            region,
            config_path=config,
            output=output,
            cache_dir=cache_dir,
            opener=_OPENER.get(),
        )
    except (ClockChangeDayError, FileNotFoundError, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    show_run_home(report, n, output)
