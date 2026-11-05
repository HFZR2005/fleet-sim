# Getting started

## Setup

You need Python 3.12 and [uv](https://docs.astral.sh/uv/). From the repository root:

```bash
uv sync
```

This installs the package, the dev tools, and the `fleet-sim` console script.

## Run the checks

```bash
uv run pytest              # tests (no network access)
uv run mypy --strict src   # type checking
uv run ruff check          # lint
uv run ruff format --check # formatting
```

Tests live in `tests/` and use saved fixtures in `tests/fixtures/`. They do not call external APIs.

## Run one home

```bash
uv run fleet-sim run-home --date 2026-10-20 --region C
```

This fetches Agile prices for that day (cached in `.cache/agile/`), solves a single home's charging schedule, and prints the bill under the no-battery, rule, and optimiser strategies.

## Run a scenario

```bash
uv run fleet-sim run-scenario scenarios/network-sweep.toml \
    --output /tmp/network-sweep \
    --max-households 100
```

This runs the network penetration sweep: 50 homes on 4 transformers, at 6 penetration levels from 0% to 100%, with 30 replications. It prints a table of overload metrics with 95% confidence intervals and writes frames, metadata, and metrics JSON to the output directory.

The first run fetches prices from the Octopus API (one request per day × region). Subsequent runs read from the cache.

## Scenario files

Scenarios are TOML files in `scenarios/`. Each defines the fleet size, penetration, dates, battery catalogue, and (optionally) a `[network]` section for transformer topology. See the [Experiments](experiments.md) page for the replication design.

| File | What it runs |
| --- | --- |
| `scenarios/diverse.toml` | Diverse fleet at full penetration, no network |
| `scenarios/identical.toml` | Paired identical fleet for diversity comparison |
| `scenarios/penetration-sweep.toml` | Fleet-metric sweep from 0% to 100%, no network |
| `scenarios/network.toml` | Full penetration on a network (single point) |
| `scenarios/network-sweep.toml` | Network overload sweep from 0% to 100% |
| `scenarios/smoke-network.toml` | Tiny network smoke test (2 homes, 1 day) |

## Serve these docs locally

```bash
uv run mkdocs serve
```

Then open [http://localhost:8000](http://localhost:8000).
