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

## Milestone 5

How much of the battery savings can coordination keep while removing the overloads? A coordinator adjusts each home's charging window so that no transformer exceeds its limit. The question is the trade-off: how many pence per home does the fleet give up, and which homes bear the cost?

## Milestone 6

Can a run be watched while it is going? Frames are written as the days finish, so a view can follow a run that is still in progress.
