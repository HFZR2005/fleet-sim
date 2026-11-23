# Roadmap

GitHub has milestones 1 and 2. Milestones 3 to 6 are the work those issues point at, and they are not milestones on GitHub yet.

## Milestone 1

What does one optimal battery do on a real Agile day? Done when `run-home` prints the no-battery, rule, and optimiser bills and saves the price, state of charge, and import figure.

## Milestone 2

What new peak appears when many identical batteries each optimise alone? Done when `run-fleet --homes 100 --start 2026-01-01 --end 2026-01-31` reports the peaks with and without batteries, writes a frame file, and saves the herding figure.

## Milestone 3

How large is the new peak, and how wide is the spread, when homes are no longer copies? Done. `fleet-sim run-scenario scenarios/diverse.toml` runs a diverse fleet for the scenario's replications, prints each metric as a mean with a 95% interval, and writes frames, metadata, and figures. Homes are drawn from Low Carbon London households rather than copied from one profile.

## Milestone 4

Where do transformer limits bind, and how does the network reach a home? Done. `fleet-sim run-scenario scenarios/network-sweep.toml` sweeps penetration from 0% to 100% on a four-transformer tree, measures overloads with 95% intervals, and compares clustered (ρ = 0.8) to unclustered (ρ = 0) ownership. Overloads first appear at 25% penetration and every transformer is overloaded at full penetration. Clustering brings overloads forward and concentrates the energy. Results are in `docs/results/milestone-4.md`.

## Milestone 4.5

How much does the wholesale price move when the fleet adds load? Done. `scripts/fit_price_curves.py` fits the price as a curve of residual load, and `finalise` writes the chosen curves to `calibration/price_curves.json`. The main model is an exponential fitted to price divided by fuel cost, with four other curve shapes and an unadjusted fit kept as robustness checks ([ADR-0004](docs/decisions/0004-price-curve-model.md)). On the held-out year, 2025, it scores 21.3 £/MWh RMSE.

## Milestone 4.6

What happens when the fleet's own charging moves the prices it schedules against? Done. `fleet-sim run-scenario scenarios/market-sweep.toml --release` solves the price equilibrium for every day, replication and (national, local) penetration pair as one linear program, and reports savings, national added load and overload metrics with 95% intervals, paired against the same fleets at historical prices. National uptake M moves the price; local uptake and clustering load the transformers. Feedback spreads the national herd, savings fall with M (to 80% at 4 million batteries under the main curve, 25–42% under the steep-evening robustness curves), and transformers stay overloaded wherever homes plan alone at the equilibrium prices. Results are in `docs/results/milestone-4.6.md`.

## Milestone 5

How much of the battery savings can coordination keep while removing the overloads? Milestone 4.6 is the baseline: prices alone. Price feedback spreads the national herd and keeps 80% of each home's saving at 4 million batteries under the main price curve, but it does not protect transformers: homes that plan alone at the equilibrium prices charge together again, and every transformer stays overloaded at full local penetration. A coordinator that also enforces transformer limits is compared against that baseline on the same fleets, topology and days. The question is the trade-off: how many pence per home does the fleet give up beyond what prices already take, and which homes bear the cost?

## Milestone 6

Can a run be watched while it is going? Frames are written as the days finish, so a view can follow a run that is still in progress.
