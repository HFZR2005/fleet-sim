"""Command line for fleet-sim."""

import contextvars
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Annotated

import typer
from typer._click.exceptions import ClickException  # Typer vendors Click

from fleet_sim.commands import run_fleet, run_home
from fleet_sim.data import AgilePriceSource
from fleet_sim.models.prices import ClockChangeDayError
from fleet_sim.render import show_run_fleet, show_run_home

_OPENER: contextvars.ContextVar[Callable[[str], bytes] | None] = contextvars.ContextVar(
    "fleet_sim_price_opener",
    default=None,
)

app = typer.Typer(
    name="fleet-sim", no_args_is_help=True, pretty_exceptions_enable=False
)
_DEFAULT_OUTPUT = Path("figures") / "day"
_DEFAULT_HERDING = Path("figures") / "herding"
_DEFAULT_PEAKS = Path("figures") / "peaks"
_DEFAULT_FRAMES = Path("frames.json")


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
            price_source=AgilePriceSource(
                cache_dir=cache_dir,
                opener=_OPENER.get(),
            ),
        )
    except (ClockChangeDayError, FileNotFoundError, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    show_run_home(report, n, output)


@app.command("run-fleet")
def run_fleet_command(
    n_homes: Annotated[int, typer.Option("--homes", help="Number of identical homes")],
    start: Annotated[
        date,
        typer.Option(
            "--start",
            parser=_parse_date,
            metavar="YYYY-MM-DD",
            help="First UK civil day",
        ),
    ],
    end: Annotated[
        date,
        typer.Option(
            "--end",
            parser=_parse_date,
            metavar="YYYY-MM-DD",
            help="Last UK civil day",
        ),
    ],
    region: Annotated[str, typer.Option(help="Octopus GSP letter, for example C")],
    config: Annotated[Path, typer.Option(help="Home config")] = Path("home.toml"),
    frames: Annotated[Path, typer.Option(help="Frame file")] = _DEFAULT_FRAMES,
    herding: Annotated[
        Path, typer.Option(help="Herding figure path without suffix")
    ] = (_DEFAULT_HERDING),
    peaks: Annotated[
        Path, typer.Option(help="Daily-peak figure path without suffix")
    ] = (_DEFAULT_PEAKS),
    cache_dir: Annotated[
        Path | None,
        typer.Option(
            help="Price cache directory (default: .cache/agile)",
            show_default=False,
        ),
    ] = None,
) -> None:
    """Run identical homes over a date range and save the herding figures."""
    try:
        report, herding_day = run_fleet(
            n_homes=n_homes,
            start=start,
            end=end,
            region=region,
            config_path=config,
            frames_path=frames,
            herding_output=herding,
            peaks_output=peaks,
            price_source=AgilePriceSource(
                cache_dir=cache_dir,
                opener=_OPENER.get(),
            ),
        )
    except (ClockChangeDayError, FileNotFoundError, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    show_run_fleet(
        report,
        n_homes=n_homes,
        region=region,
        frames_path=frames,
        herding_path=herding,
        peaks_path=peaks,
        herding_day=herding_day,
    )
