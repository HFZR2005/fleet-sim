---
covers:
  - commands/market.py
  - fleet/market.py
  - fleet/price_inputs.py
  - viz/market.py
---

# The fleet in the loop: prices that respond to the fleet

Up to milestone 4 every battery scheduled against the historical Agile price, as if the fleet were too small to move it. Here the price responds to the fleet's own charging through the fitted price curve, and each day is solved for the equilibrium: every home's schedule is optimal at the prices the whole fleet causes (`docs/formulation.md`, Fleet in the loop). The questions are whether price feedback alone spreads the herd, how much of each home's saving survives as the national fleet grows, and whether it protects transformers.

## Setup

`scenarios/market-sweep.toml`: fifty homes on the milestone-4 four-transformer tree, region C, 5–11 January 2026, master seed 1, 10 replications. Two sweep axes. National uptake M, the number of batteries in Great Britain, is 0, 0.5, 1, 2 and 4 million; it sets how much load the fleet adds, so it moves the price. Local penetration, the share of the fifty homes with a battery, is 10, 25, 50 and 100%, with ρ = 0 and ρ = 0.8; it loads the transformers. Price model `fuel_adjusted/exponential`, 40 segments per slot, equilibrium tolerance 1 p per home per day. The headline point (ρ = 0, local penetration 100%) is repeated under `fuel_adjusted/signed_quadratic` and `fuel_adjusted/cubic`, the upper bracket for the evening slope ([ADR-0004](../decisions/0004-price-curve-model.md)).

Each number is the mean of the 10 replications, and the range in brackets is the 95% t-interval. A replication draws one fleet; the metric is the mean over its seven days. Every M is paired with M = 0 on the same fleets, topology and days, and a "change" is the paired difference. The machine-readable results are in `docs/results/milestone-4.6.json`. The run was 3,500 fleet-day solves in 409 s. Demand is the first 100 households in the Low Carbon London file, as in milestone 4. The 2026 price inputs (Agile rates, NESO demand, Elexon wind, gas and carbon prices) were downloaded by the milestone-4.5 loaders. On an empty cache the first attempt stopped at 6 January with "no Agile rate for 48 of 48 slots": `load_agile_rates` had cached a partial January, fetched for 5 January only, under the whole month's key. Removing that file so the month was fetched whole let the run complete on the scenario's own dates.

The decomposition and peak-per-home numbers below are not in the sweep's output. `scripts/decompose_market_saving.py` re-solves the headline point on the same fleets and prints them.

With M = 0 the run is the milestone-4 run. At full local penetration it gives 529.0 kWh (464.8 to 593.2) of overload energy over 10 replications, against 548.8 kWh (517.0 to 580.5) over 30 in milestone 4.

## Does price feedback alone spread the herd?

Nationally, partly. At historical prices the fleet charges together. The largest net battery power, over the week's slots, is 4.22 kW (4.11 to 4.33) per battery home: 4.2 GW per million batteries if the national fleet behaved like the simulated one. In the loop the price rises in the slots the fleet crowds into, and the fleet spreads its charging over more of the night.

| M (million) | Peak added load (GW) | Per million batteries (GW) | Peak of the mean day (GW per million) |
| ---: | --- | ---: | ---: |
| 0 (historical) | – | 4.22 (4.11 to 4.33) | 2.51 at 03:30 |
| 0.5 | 1.99 (1.91 to 2.08) | 3.99 | 2.05 at 22:30 |
| 1 | 3.50 (3.41 to 3.60) | 3.50 | 1.79 at 22:30 |
| 2 | 4.65 (4.40 to 4.89) | 2.32 | 1.34 at 22:30 |
| 4 | 8.82 (8.33 to 9.31) | 2.21 | 0.97 at 22:30 |

Headline point, main model. The last column is the highest slot of the mean day, the curve drawn in the figure. At 0.5 million batteries feedback barely spreads the herd: the peak is about 95% of what the same batteries would add at historical prices. At 1 million it is 83%, and at 2 and 4 million 55% and 52%. The national peak still grows with M, from 2.0 to 8.8 GW, but more slowly than the fleet: eight times the batteries add 4.4 times the peak.

The evening is unchanged. Discharging is capped by each home's own demand, since homes do not export, so at 16:30–18:30 the fleet supplies about 0.8 kW per battery home at every M. Feedback reshapes only the charging.

The peak moves to 22:00–23:00 in every replication with M > 0. At M = 0 the largest slot falls at 03:00 in three replications and at 22:00 in seven, so the reported mean hour, 16.3 (9.7 to 22.9), is the average of two clusters, not a time of day.

![Added load per million batteries over the day, at each M, headline point](../added_load.svg)

## How much of each home's saving survives?

Saving per battery home, headline point, p/day. The paired change from M = 0 is in the second line of each cell.

| M (million) | Exponential (main) | Signed quadratic | Cubic |
| ---: | --- | --- | --- |
| 0 | 79.41 (75.63 to 83.19) | 79.41 | 79.41 |
| 0.5 | 74.64 (71.13 to 78.15)<br>−4.77 (−5.09 to −4.44) | 67.67 (64.68 to 70.67)<br>−11.74 (−12.57 to −10.90) | 65.16 (62.44 to 67.88)<br>−14.25 (−15.33 to −13.17) |
| 1 | 71.80 (68.47 to 75.13)<br>−7.61 (−8.12 to −7.10) | 60.21 (57.76 to 62.67)<br>−19.20 (−20.58 to −17.81) | 55.37 (53.40 to 57.34)<br>−24.04 (−25.90 to −22.18) |
| 2 | 68.29 (65.14 to 71.44)<br>−11.12 (−11.82 to −10.42) | 49.23 (47.58 to 50.88)<br>−30.18 (−32.38 to −27.99) | 40.46 (39.69 to 41.24)<br>−38.95 (−41.98 to −35.91) |
| 4 | 63.43 (60.59 to 66.26)<br>−15.99 (−17.00 to −14.97) | 33.28 (32.94 to 33.61)<br>−46.13 (−49.63 to −42.64) | 19.73 (19.07 to 20.39)<br>−59.68 (−64.11 to −55.25) |

Under the main model a home keeps 94% of its historical-price saving at 0.5 million batteries, 90% at 1 million, 86% at 2 million and 80% at 4 million. The paired intervals are narrow because the same fleets are compared at every M. Under the two robustness models, which put the evening slope two to six times higher, a home keeps 76% and 70% at 1 million, and 42% and 25% at 4 million. How much survives beyond about 1 million batteries depends on the shape of the curve more than on anything else in the run.

The saving depends only on the national added load b*, so it is the same whichever homes supply it (`docs/formulation.md`, Market measures).

![Saving per battery home against national batteries M, three price models, headline point](../saving_by_model.svg)

### Price change without a battery

At the headline point a home's demand, with no battery, costs 0.19 (0.12 to 0.25) p/day more at 0.5 million batteries, 0.32 (0.20 to 0.44) at 1 million and 0.55 (0.12 to 0.98) at 4 million, under the main model: the fleet's charging raises night prices by more than its discharging lowers evening ones, weighted by when homes use power. Under the robustness models the sign reverses. Evening prices fall so far that the same demand costs 5.70 (4.80 to 6.60) p/day less at 1 million under the signed quadratic and 12.00 (10.47 to 13.54) less under the cubic.

This measure averages over every simulated home's demand, with or without a battery. At local penetration 100% no simulated home lacks one, so it is the price effect on household demand, not the bill of an actual home without a battery (`docs/formulation.md`, Market measures). It is close to the same at every local penetration, since demand is drawn the same way for every home.

## Does the spread narrow mostly from the cheap end?

`docs/results/price-curves.md` predicted, from the fitted curve alone, that a growing fleet would raise its buying prices faster than it lowers its selling prices, so its spread would narrow mostly from the cheap end. Under the main model it does.

Holding the M = 0 schedules fixed, the slots where the herd charged become dearer and the slots where it discharged become cheaper (headline point, p/kWh, `scripts/decompose_market_saving.py`):

| M (million) | Where the herd charged | Where it discharged |
| ---: | --- | --- |
| 0.5 | +0.61 (0.60 to 0.63) | −0.07 (−0.08 to −0.07) |
| 1 | +0.98 (0.95 to 1.00) | −0.15 (−0.15 to −0.14) |
| 2 | +1.40 (1.37 to 1.44) | −0.28 (−0.29 to −0.26) |
| 4 | +1.97 (1.93 to 2.01) | −0.52 (−0.55 to −0.48) |

The saving lost at 4 million batteries, 16.0 p/day, splits into 14.1 p from dearer charging, 3.3 p from cheaper discharging, and 1.4 p won back by re-scheduling. About four-fifths of the loss is at the cheap end.

The fleet's mean charging and discharging prices from the sweep do not show this directly. At 4 million the mean charging price rises by 2.04 (2.00 to 2.09) p/kWh and the mean discharging price by 3.06 (2.94 to 3.18) p/kWh: the realised spread widens. The fleet cycles less, 5.3 kWh a day charged per battery home at 4 million against 7.1 at M = 0, and keeps its dearest discharging slots. The mean prices measure where the fleet chooses to trade, not how the prices moved.

The prediction depends on the price model. Under the cubic, cheaper discharging costs more than dearer charging from 1 million batteries up (13.3 against 11.6 p/day at 1 million, 38.4 against 23.0 at 4 million), and the mean discharging price falls by 2.59 (2.02 to 3.16) p/kWh at 4 million. Under the signed quadratic the two ends are about equal at 4 million (24.1 against 24.1 p/day). This matches the reversed slope ordering of those families in `docs/results/price-curves.md`.

## Does it protect transformers?

Not where batteries cluster, and elsewhere only under one allocation that nothing in the prices selects. The answer depends on which homes supply the national added load, which the equilibrium does not settle.

Every home takes prices as given, so the equilibrium fixes b*, the national load, but not who supplies it. The linear program returns one corner, chosen by the solver; other splits of the same b* are also equilibria (`docs/formulation.md`, Open choices). Two allocations are reported. **Joint** runs the program's own schedules. **Re-planned** runs each home's own best schedule at the equilibrium prices, which is what a home would do if it planned alone.

Share of transformers overloaded and overload energy at local penetration 100%, main model (ρ = 0 and ρ = 0.8 coincide here, since every home has a battery):

| M (million) | Overloaded, joint | Overloaded, re-planned | Energy, joint (kWh) | Energy, re-planned (kWh) |
| ---: | --- | --- | --- | --- |
| 0 | 1.00 | 1.00 | 529.0 (464.8 to 593.2) | 529.0 |
| 0.5 | 1.00 | 1.00 | 229.1 (198.1 to 260.0) | 495.8 (437.9 to 553.7) |
| 1 | 1.00 | 1.00 | 126.0 (101.0 to 150.9) | 456.8 (402.3 to 511.3) |
| 2 | 0.80 (0.72 to 0.88) | 1.00 | 46.4 (30.0 to 62.9) | 428.2 (376.4 to 480.1) |
| 4 | 0.57 (0.45 to 0.70) | 1.00 | 22.1 (11.1 to 33.1) | 385.2 (337.3 to 433.1) |

Under the joint allocation feedback relieves transformers: at 4 million batteries overload energy falls by 506.9 kWh (449.3 to 564.5). But up to 1 million batteries every transformer is still overloaded. And the relief comes from the corner the solver returned: each home's joint schedule is optimal at the equilibrium prices, but so are others, and nothing in the prices makes a home choose this one. Re-planned, every home picks its own cheapest slots at nearly flat night prices and they herd again. The fleet's peak net power is back at 4.19 kW (4.08 to 4.29) per battery home at 4 million, against 4.22 at historical prices. Every transformer stays overloaded at every M, and overload energy falls by only 72.2 kWh (61.6 to 82.8) at 1 million and 143.8 kWh (122.0 to 165.6) at 4 million.

Where batteries cluster (ρ = 0.8) at low local penetration, the re-planned share overloaded does not move with M: 0.23 (0.17 to 0.28) at 25% and 0.55 (0.44 to 0.66) to 0.53 (0.42 to 0.63) at 50%. The price responds to national uptake, while a transformer's load depends on the homes under it. A cluster of batteries on one transformer sees the same national price as everyone else and charges together under it. The joint allocation does relieve clustered transformers, to 0.07 (−0.01 to 0.16) at 25% and 4 million, but for the reason above nothing makes homes follow it.

![Share of transformers overloaded against local penetration, one line per M, joint and re-planned, ρ = 0 and 0.8](../overload_by_penetration.svg)

## What depends on what

- **On the allocation:** every overload result, and the mean charging and discharging prices (which weight by each home's own charging, not by b*). The joint and re-planned allocations bracket what the transformers see; neither is a prediction.
- **Not on the allocation:** the national added load and its peak, the saving per battery home, and the price change without a battery. These depend only on b*, which every equilibrium shares.
- **On the price model:** how much saving survives beyond about 1 million batteries, the sign of the price change without a battery, and whether the spread narrows from the cheap or the dear end. The main model and its two robustness models agree that the fleet spreads its charging and that savings fall with M; they disagree on how far.

## Diagnostics

Worst over the run, every point, model and day:

- **Linearisation error.** 3.30 p/kWh, under the cubic at 4 million batteries. Under the main model at the headline point it is 0.05, 0.10, 0.20 and 0.38 p/kWh at 0.5, 1, 2 and 4 million. It grows with M because a larger fleet stretches each segment over more of the curve.
- **(MODE) breaks.** None. No home charged and discharged in the same slot.
- **Equilibrium tolerance.** The largest re-plan saving was 37.67 p, under the cubic at 4 million. Of 3,500 fleet-days, 1,214 had a home that could save more than 1 p by re-solving alone. Under the main model no fleet-day was flagged at 0.5 or 1 million batteries; at 2 million 264 of 560 were, and at 4 million 509 of 560, with the largest saving 4.41 p. Under the robustness models flags start at 0.5 million.
- **Re-planned load difference.** Up to 18.9 GW (16.4 GW at the headline point at 4 million): homes re-planning alone add a national load far from b*. This is the herding of the last section, not an error.
- **Out-of-range slots.** One fleet-day, at 4 million batteries and 10% local penetration, had one slot where R + b left the curve's 2021–2024 range.

The tolerance flags come from the segment approximation. `scenarios/market-segments-160.toml` repeats the headline point at 2 and 4 million with 160 segments instead of 40. The linearisation error falls from 0.38 to 0.09 p/kWh at 4 million, the largest re-plan saving from 4.39 to 1.17 p, and the flagged fleet-days from 46 of 70 to 0 at 2 million and from 69 of 70 to 2 at 4 million. The results barely move: saving per battery home 63.48 (60.64 to 66.32) p/day against 63.43, and peak added load 8.86 (8.42 to 9.31) GW against 8.82 at 4 million. The robustness models, whose curves are steeper, were not re-run; their flags are larger and their results at high M carry more approximation error.

## Limits

One week of January 2026, one region, fifty homes and 10 replications. The paired intervals are narrow, but they measure the spread between fleets drawn from the same hundred households, not between weeks or seasons. The national fleet is assumed to behave like the simulated one. Homes do not export, so the fleet can only lower evening prices by covering its own demand. Coordination, and enforcing transformer limits, are milestone 5.
