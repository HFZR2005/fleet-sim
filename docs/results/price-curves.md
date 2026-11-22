---
covers:
  - prices/pipeline.py
  - prices/evaluation.py
  - calibration/price_curves.json
---

# Price curves: how much the fleet moves the price

How much does the GB wholesale price rise when demand rises by a gigawatt? That is what a fleet of batteries does to the price when it charges in the same half-hours. This page gives the fitted answer. The model choice behind it is [ADR-0004](../decisions/0004-price-curve-model.md).

## Setup

Half-hourly wholesale prices from 1 May 2021 to 31 December 2025, recovered from Agile region C. Residual load $`R`$ is national demand minus renewables. Fuel cost $`k`$ is the cost of running a gas plant (heat rate 2.0, gas carbon intensity 0.184 t/MWh, with the carbon price support). Training years are 2021–2024 and the final-test year is 2025, read once.

A pooled model is scored on each training year after being fitted to the other three. "Where the fleet charges" and "where it discharges" weight each half-hour by the battery power of the `identical` scenario's uncoordinated fleet run on that day's Agile prices. Slopes are in £/MWh of wholesale price per GW of residual load. Divide by 10 for p/kWh per GW. For scale, 1 GW is roughly 200,000–280,000 home batteries charging at 3.6–5 kW.

The full tables are written by `scripts/fit_price_curves.py compare` to `results/price-curves/comparison.md`.

## Fuel cost sets the level

Divided by fuel cost, the four training years fall on one curve. Held-out RMSE on exact slots, £/MWh, exponential family:

| Target | 2021 | 2022 | 2023 | 2024 |
| --- | ---: | ---: | ---: | ---: |
| Raw price, pooled | 46.4 | 92.4 | 46.2 | 60.9 |
| Price ÷ fuel cost | 20.1 | 35.9 | 21.0 | 19.4 |

Most of the year-to-year change in price comes from gas and carbon prices, not from load. A curve fitted on past years can therefore be used in a new year by scaling it with that year's fuel cost.

## An extra gigawatt raises the price by about £4–6/MWh where the fleet charges

Main model (`fuel_adjusted/exponential`), mean slope weighted by fleet battery power:

| Year | Where the fleet charges | Where it discharges |
| --- | ---: | ---: |
| 2021 | 5.1 | 3.4 |
| 2022 | 6.4 | 3.9 |
| 2023 | 4.6 | 3.4 |
| 2024 | 3.8 | 2.7 |
| 2025 (final test) | 4.4 | 3.1 |

The slope tracks fuel cost: it is highest in 2022 and lowest in 2024. In 2025 one extra GW of charging raises the wholesale price by about 0.44 p/kWh in the half-hours where the fleet charges.

## The curve is steeper where the fleet charges

In every year the slope is higher where the fleet charges than where it discharges, by a factor of 1.3–1.6. The fuel-adjusted curve is concave: steep at low residual load, flattening as load rises. Most of the fleet's charging falls at 5–15 GW of residual load, and most of its discharging at 15–25 GW, where the curve is flatter (`slopes` figure).

If this holds when the fleet is in the loop, a growing fleet raises the prices it buys at faster than it lowers the prices it sells at, and its arbitrage spread narrows mostly from the cheap end. That is a property of the fitted curve, not a simulated result yet. Running the fleet against prices that respond to its own charging is the next milestone.

## The shape of the curve matters most where the fleet discharges

The same slopes for every family, fuel-adjusted target, training years 2021–2024:

| Family | Charging | Discharging |
| --- | --- | --- |
| Exponential (main) | 5.1, 6.4, 4.6, 3.8 | 3.4, 3.9, 3.4, 2.7 |
| Cubic with offset | 4.6, 5.9, 3.8, 3.1 | 3.8, 4.4, 3.4, 2.6 |
| Isotonic | 5.1, 6.3, 5.1, 4.8 | 3.9, 5.9, 3.7, 2.8 |
| Signed quadratic | 7.5, 12.0, 5.4, 3.9 | 11.8, 17.7, 8.8, 6.8 |
| Cubic | 5.8, 11.0, 4.2, 2.8 | 13.9, 22.7, 10.2, 7.7 |

The three families that fit the data agree within about 1.7 £/MWh per GW where the fleet charges. The cubic and signed quadratic are forced through zero price at zero load and fit badly, with two to three times the error. They put the evening slope two to six times higher, and they reverse the ordering above: steeper where the fleet discharges. Results that depend on the evening slope are therefore reported under these two families as well, as an upper bracket.

## Final test

Every chosen model was refitted on 2021–2024 and scored once on 2025. RMSE on exact slots, £/MWh:

| Model | 2025 |
| --- | ---: |
| `fuel_adjusted/exponential` (main) | 21.3 |
| `fuel_adjusted/cubic_offset` | 21.8 |
| `fuel_adjusted/isotonic` | 20.0 |
| `fuel_adjusted/signed_quadratic` | 47.6 |
| `fuel_adjusted/cubic` | 63.3 |
| `raw_per_year/exponential` (fitted to 2025) | 21.9 |

The main model's error on 2025 is within the 19–36 £/MWh range of the training years. Its parameters are in `calibration/price_curves.json`, and later milestones read them with `load_price_model`.
