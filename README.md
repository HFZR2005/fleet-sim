# fleet-sim

A simulator of UK home batteries scheduled against half-hourly electricity prices (Octopus Agile), scaling from one home to a fleet, to study how fleets of individually optimal batteries create new demand peaks and how coordination strategies trade savings against peak reduction.

## Quickstart

```bash
uv sync
uv run pytest
uv run mypy --strict src
uv run ruff check
uv run ruff format
```

## One home

```bash
uv run fleet-sim run-home --date 2026-10-20 --region C
```

`home.toml` holds the battery and the half-hourly demand. The command fetches that day's Agile import prices, runs the cheapest-slot rule and the optimiser, prints both bills against the no-battery bill, and writes `figures/day.svg` and `figures/day.png`.

For 20 October 2026 in region C the bills were 604.05 pence with no battery, 506.05 pence with the rule (`n = 8`), and 480.78 pence with the optimiser. The rule kept 0.795 of the optimal saving. The figure below is that run, written with `--output docs/day`.

![Price, state of charge, and grid import for one home on 20 October 2026, region C](docs/day.svg)
