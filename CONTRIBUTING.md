# Contributing

## Setup

Python 3.12 and [uv](https://docs.astral.sh/uv/). From the repository root:

```bash
uv sync
```

That installs the package and the checks. The console script is `fleet-sim`.

## Tests and checks

```bash
uv run pytest
uv run mypy --strict src
uv run ruff check
uv run ruff format --check
```

Tests live in `tests/` and do not use the network. Saved responses are in `tests/fixtures/`. A change in behaviour comes with a test. Tests exist to catch a wrong answer, so prefer fewer, stronger ones:

- Test each acceptance criterion through the public function, not private helpers.
- Every equation gets one case small enough to solve by hand, with the working in a comment. Keep a worked case in one test with several asserts.
- Put several inputs to the same rule in one `@pytest.mark.parametrize` table.
- Don't test what Pydantic, mypy or a library already guarantee, and don't test a shared mechanism (caching, opener injection, clock-change rejection) in every module that uses it.
- Put repeated setup in a fixture or `conftest.py`.

## Workflow

Every change belongs to one GitHub issue. The acceptance criteria are the definition of done, and the "Out of scope" section is a hard limit.

Work for one milestone goes on one branch. Each issue is one commit on that branch. The pull request is for the milestone, and its description says which issues it closes (`Closes #12`).

The maths is specified in `docs/formulation.md`. If the code and that document disagree, stop and say so.

## Where code goes

Data that crosses a module boundary is a Pydantic model. Units go in the name (`capacity_kwh`, `price_p_per_kwh`). State of charge and efficiencies are fractions in `[0, 1]`. A function that implements an equation names that equation in its docstring and points at the section of `docs/formulation.md`.

| Path | What belongs there |
| --- | --- |
| `src/fleet_sim/models/` | Pydantic types at a module boundary |
| `src/fleet_sim/data/` | Price and demand sources |
| `src/fleet_sim/optimise/` | The one-home solver and the cheapest-slot rule |
| `src/fleet_sim/fleet/` | Fleet construction, the network, solving, measures, multi-day runs, frame files |
| `src/fleet_sim/viz/` | Figures. A figure reads its inputs; it does not solve |
| `src/fleet_sim/commands/` | Command logic |
| `src/fleet_sim/render/` | Rich views of a command's result |
| `src/fleet_sim/cli.py` | Wiring a command to its view |

`commands/` does not import `render/`. `render/` does not import `commands/`.
