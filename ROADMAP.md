# Roadmap

GitHub has milestones 1 and 2. Milestones 3 to 6 are the work those issues point at, and they are not milestones on GitHub yet.

## Milestone 1

What does one optimal battery do on a real Agile day? Done when `run-home` prints the no-battery, rule, and optimiser bills and saves the price, state of charge, and import figure.

## Milestone 2

What new peak appears when many identical batteries each optimise alone? Done when `run-fleet --homes 100 --start 2026-01-01 --end 2026-01-31` reports the peaks with and without batteries, writes a frame file, and saves the herding figure.

## Milestone 3

How large is the new peak, and how wide is the spread, when homes are no longer copies? Homes differ, drawn at random from a smart-meter demand profile, and the report is a confidence interval rather than the min and max of identical copies.

## Milestone 4

Where do transformer limits bind, and how does the network reach a home? The topology and the limits live in `Network`. A home still only sees the network as a price adjustment.

## Milestone 5

How much bill saving is given up to cut the peak, and who gives it up? Coordination trades a home's saving against the fleet peak, and the result says which homes give the saving up.

## Milestone 6

Can a run be watched while it is going? Frames are written as the days finish, so a view can follow a run that is still in progress.
