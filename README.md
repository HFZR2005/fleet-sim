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

## A fleet

```bash
uv run fleet-sim run-fleet --homes 100 --start 2026-01-01 --end 2026-01-31 --region C
```

The command builds 100 copies of `home.toml`, solves each day on its own, and prints the median, minimum, and maximum of the fleet measures. It writes `frames.json`, plus `figures/herding` and `figures/peaks` as SVG and PNG.

For January 2026 in region C the median peak was 560.00 kW with the batteries and 150.00 kW without them. Without batteries that peak is the evening demand of the hundred homes, and it does not change from day to day. Charging lifts it: the highest peak was 650.00 kW, on 2 January. The median saving was 97.16 pence per home. The figure below is that day's import and price, written with `--herding docs/herding --peaks docs/peaks`.

![Fleet import with and without batteries on 2 January 2026, region C, 100 homes](docs/herding.svg)

## Findings

```bash
uv run fleet-sim run-scenario scenarios/diverse.toml
```

The command reads the scenario, draws each replication from the Low Carbon London file in `.cache/lcl`, and prints every metric as a mean with a 95% interval. It writes frames and metadata under `scenario-out/`, and saves the diversity and penetration figures there.

Eight homes, region C, 5–11 January 2026, thirty replications. Demand is the first 100 households in that file. A diverse fleet peaks 3.57 kW below identical copies of the same mean home (95% interval −4.34 to −2.80 kW). One battery in the eight is enough for the fleet peak to rise above the no-battery peak, and at full penetration the peak is 26.19 kW higher. The curve is the six penetrations in `scenarios/penetration-sweep.toml`.

![Peak demand with and without batteries against penetration, eight homes, region C, 5–11 January 2026](docs/penetration.svg)
