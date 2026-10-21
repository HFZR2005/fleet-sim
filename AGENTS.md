# [AGENTS.md](http://AGENTS.md)

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

## Code conventions

- Python 3.12, `src/` layout, managed with `uv`.
- Data crossing a module boundary goes through a Pydantic model (e.g. `BatterySpec`, `PriceSeries`, `Schedule`). Do not pass raw dicts or bare arrays between modules.
- Units go in names: `capacity_kwh`, `max_charge_kw`, `price_p_per_kwh`. A slot is 30 minutes, so energy per slot is `power_kw * 0.5`.
- Fractions, not percentages: state of charge and efficiencies are in [0, 1]. Validate this.
- Any function implementing an equation states that equation in its docstring and references the section of `docs/formulation.md`.
- Type everything; `mypy --strict` must pass. `ruff check` and `ruff format` must pass.
- Prefer clear code over clever code. No metaprogramming, no premature abstraction.



## Tests

- Every behaviour change comes with tests in `tests/`.
- Tests never touch the network. Use the fixture files in `tests/fixtures/`.
- Optimiser tests include at least one case small enough to solve by hand, with the expected answer worked out in a comment.
- Random behaviour takes an explicit seed.



## Do not

- Do not commit downloaded data; it is cached outside the repo (see `.gitignore`).
- Do not set arguments explicitly when the library default is correct.
- Do not silence type or lint errors with ignores unless the issue says to.

