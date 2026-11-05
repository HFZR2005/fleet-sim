---
covers: []
---

# fleet-sim

A simulator of UK home batteries scheduled against half-hourly electricity prices ([Octopus Agile](https://octopus.energy/smart/agile/)), scaling from one home to a fleet, to study how fleets of individually optimal batteries create new demand peaks and how coordination strategies trade savings against peak reduction.

Each home solves its own cheapest-charging problem. When many homes do this against the same prices, their charging aligns and the fleet's peak demand rises — a phenomenon sometimes called **herding**. The simulator measures this effect across penetration levels and transformer topologies, with confidence intervals from independent replications.

## What's in these docs

**[Getting started](getting-started.md)** — install, run the tests, run your first experiment.

**Background**

- [UK energy context](background.md) — the Agile tariff, the distribution network, transformer ratings, and a glossary of terms. Start here if you're not familiar with the UK energy system.
- [Pipeline overview](pipeline.md) — visual walkthrough of the simulation stages, from price data to overload metrics.

**Reference**

- [Formulation](formulation.md) — the mathematical specification: notation, constraints, objective, fleet and network extensions.
- [Architecture](architecture.md) — the code stages and the Pydantic types that connect them.
- [Assumptions](assumptions.md) — modelling choices a reader should question.
- [Experiments](experiments.md) — replication design, t-intervals, and paired comparisons.
- [Household demand](household-demand.md) — the Low Carbon London dataset, day matching, and completeness rules.
- [Output format](frames.md) — the JSON schema for per-slot simulation frames.

**Results**

- [Milestone 3 — Diversity](results/milestone-3.md) — diverse vs identical fleets, and peak demand against penetration.
- [Milestone 4 — Overloads](results/milestone-4.md) — transformer overloads against penetration, with and without clustering.

**Decisions**

- [ADR-0001: Network as a price](decisions/0001-network-as-a-price.md) — why the network constraint reaches homes through a price adjustment, not a direct signal.
