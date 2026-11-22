# AGENTS.md

Instructions for AI coding agents (Cursor, Claude Code) working in this repository. Human contributors should read CONTRIBUTING.md; this file is the same conventions written for an agent.

## What this project is

A simulator of UK home batteries scheduled against half-hourly electricity prices (Octopus Agile), scaling from one home to a fleet, to study how fleets of individually optimal batteries create new demand peaks and how coordination strategies trade savings against peak reduction.

The maths is specified in `docs/formulation.md`. Code implements that document; if they disagree, stop and say so rather than picking one.

## How work is done

- Every change belongs to one GitHub issue. Work only on what that issue's acceptance criteria describe. Do not touch files outside its scope; if something else needs changing, say so in your summary instead of changing it.
- Keep each change small enough for a human to review in one sitting. If an issue looks too large, propose a split before writing code.
- Ask before adding any dependency.
- Finish with a short summary: what changed, why, and any decision you made that the issue didn't specify.

## Issues

- Read the issue you're working on with `gh issue view <number>` before planning.
- Treat its acceptance criteria as the definition of done, and its "Out of scope" section as a hard limit.
- Don't create, edit, comment on or close issues. Issues close when the PR that says "Closes #<number>" merges.

## Stubs

The codebase may contain stubs: functions that return placeholder data while the real implementation is pending. Placeholder output must never be mistaken for a result.

- Every stub is registered with the `@stub("reason")` decorator. Any function returning placeholder data is a stub, however small.
- A stub takes and returns the real types for its stage (e.g. `Fleet`, `PowerProfile`, `NodeFeedback`). Don't change an interface just to make a stub easier.
- Never write unmarked placeholder logic: no hard-coded "realistic-looking" numbers, no simplified versions presented as real. If you can't implement something fully within the issue's scope, leave a marked stub and say so in your summary.
- When you replace a stub, remove its decorator in the same PR and add tests that would fail against the stub.
- Outputs produced while any stub is active must say so (`STUB` prefixes, figure watermarks), and `--release` runs fail. Don't remove or weaken these markers.

## Codebase map

```
src/fleet_sim/
  models/          Pydantic boundary types (BatterySpec, Schedule, PriceSeries, Scenario, …).
                   All use ConfigDict(extra="forbid", frozen=True). Units in field names.
  data/            Data loaders. PriceSource protocol (source.py), DemandProfile protocol
                   (demand.py), Agile prices (agile.py), household demand (households.py).
  commands/        One module per CLI command. Thin orchestrators that load config,
                   call domain logic, and return a result for the render layer.
  fleet/           Fleet generation (generate.py), home solving (solve.py), network
                   aggregation (network.py), topology (topology.py), overload metrics.
  optimise/        Home-level LP/MILP solver (home.py) and rule-based fallback (rule.py).
  coordination/    Fleet coordination strategies (currently empty, milestone 5).
  experiments/     Sweep and report logic for multi-replication experiments.
  render/          Rich console output for each command.
  viz/             Matplotlib figures. apply_style() and style_axes() from style.py,
                   save_figure(fig, stem) from save.py writes SVG + PNG.
  stubs.py         @stub("reason") decorator. Tracks which stubs ran per invocation.
  cli.py           Typer app. Wires commands, catches domain errors, exposes --release.
  scenario.py      Loads and validates scenario TOML files.
```

## Canonical examples

When exploring how the codebase does something, start with these files rather than reading broadly:

- **Pydantic model**: `models/home.py` — validators, unit-named fields, frozen config
- **Protocol**: `data/source.py` (`PriceSource`) — structural subtyping, no base class
- **TOML loading**: `scenario.py` — `tomllib.loads` → `model_validate`, error wrapping
- **CLI command**: `commands/run_home.py` → wired in `cli.py`
- **Test with fixtures**: `tests/test_agile.py` — fixture files, opener injection, no network
- **Stub tracking**: `commands/network.py` — `begin_stub_run`, `active_stubs`, `require_no_stubs`
- **Figures**: `viz/network.py` — `apply_style`, `style_axes`, `save_figure`

## Code conventions

- Python 3.12, `src/` layout, managed with `uv`.
- Data crossing a module boundary goes through a Pydantic model (e.g. `BatterySpec`, `PriceSeries`, `Schedule`). Do not pass raw dicts or bare arrays between modules.
- Units go in names: `capacity_kwh`, `max_charge_kw`, `price_p_per_kwh`. A slot is 30 minutes, so energy per slot is `power_kw * 0.5`.
- Fractions, not percentages: state of charge and efficiencies are in [0, 1]. Validate this.
- Any function implementing an equation states that equation in its docstring and references the section of `docs/formulation.md`.
- Type everything; `mypy --strict` must pass. `ruff check` and `ruff format` must pass.
- Prefer clear code over clever code. No metaprogramming, no premature abstraction.

## Tests

Tests exist to catch a wrong answer, not to restate the code. Prefer fewer, stronger tests.

What to test:

- Every behaviour change comes with tests in `tests/`: one per acceptance criterion, through the public function. Don't test `_private` helpers directly.
- Every equation gets one case small enough to solve by hand, with the working in a comment. One worked case is one test with several asserts; don't split it into a test per field.
- Several inputs to the same rule (rate tables, boundaries, invalid values) go in one `@pytest.mark.parametrize` table, not one test each.
- A replaced stub needs at least one test that fails against the stub, not more because of it.

What not to test:

- What Pydantic, mypy or the library already guarantee: field types, `extra="forbid"`, that a valid model constructs, `isinstance` on return values. Do test custom validators and their messages.
- A shared mechanism (cache read/write, opener injection, clock-change rejection) more than once. Test it where it's implemented, plus one end-to-end CLI test.
- The same behaviour at several layers. Test the lowest layer that owns it.

Mechanics:

- Tests never touch the network. Use the fixture files in `tests/fixtures/`; put repeated setup in a fixture or `conftest.py` instead of copying it.
- Random behaviour takes an explicit seed.
- If a module's tests are longer than the module itself, say why in your summary.

## Do not

- Do not commit downloaded data; it is cached outside the repo (see `.gitignore`). Derived calibration files under `calibration/` (e.g. `price_curves.json`) are committed.
- Do not set arguments explicitly when the library default is correct.
- Do not silence type or lint errors with ignores unless the issue says to.
