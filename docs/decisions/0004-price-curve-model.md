---
covers:
  - calibration/price_curves.toml
  - prices/parameters.py
---

# Exponential, fuel-adjusted price curve

The main price model is **`fuel_adjusted/exponential`**: price divided by fuel cost, $`y = \pi / k`$, fitted as $`h(R) = \alpha + \beta\,(e^{\gamma R} - 1)/\gamma`$ on all training years pooled. Later milestones use it.

Results are also reported against five robustness models: the other four families on the same target (`cubic_offset`, `isotonic`, `signed_quadratic`, `cubic`), and `raw_per_year/exponential`.

The evidence is the `compare` run on training years 2021–2024, written to `results/price-curves/`: the table in `comparison.md` and the figures in `figures/`. Every number below is from those, scored on held-out years. The final-test year, 2025, was not looked at.

## Target: fuel-adjusted

`fuel_adjustment.png` shows why. Against residual load $`R`$, the raw price in 2022 sits far above the other years: the gas crisis moved the whole curve. Divided by fuel cost $`k`$, the four years fall on one curve. Supply-curve shape then comes from $`R`$, and the level from $`k`$.

Held-out RMSE on exact slots, £/MWh, exponential family:

| Target | 2021 | 2022 | 2023 | 2024 |
| --- | ---: | ---: | ---: | ---: |
| Raw, pooled | 46.4 | 92.4 | 46.2 | 60.9 |
| Fuel-adjusted | 20.1 | 35.9 | 21.0 | 19.4 |

The other families show the same gap. Raw per-year fits are scored in-sample, since each year has its own curve, so their RMSEs are not compared here.

## Family: exponential

`fits.png` and `slopes.png` show the five families. Held-out RMSE on the fuel-adjusted target, £/MWh:

| Family | 2021 | 2022 | 2023 | 2024 |
| --- | ---: | ---: | ---: | ---: |
| Cubic | 63.7 | 107.6 | 67.5 | 56.9 |
| Signed quadratic | 46.4 | 84.2 | 50.3 | 41.2 |
| Cubic with offset | 20.3 | 36.6 | 21.6 | 19.8 |
| Exponential | 20.1 | 35.9 | 21.0 | 19.4 |
| Isotonic | 19.0 | 35.4 | 21.6 | 18.9 |

- **Cubic and signed quadratic** pass through $`h(0) = 0`$ with one parameter. They sit below the data at low $`R`$ and far above it at high $`R`$, with two to three times the error of the others.
- **Isotonic** fits as well as any family, but it is a step function. Its slope $`h'(R)`$ is zero across most steps and spikes between them (`slopes.png`). The slope is what sets how much the fleet's own load moves the price, so a step function is no use as the main model.
- **Cubic with offset** fits as well as the exponential. Its slope $`a_1 + 3 a_3 R^2`$ can change sign, and it does: in 2021, 2022 and 2024 the fitted slope turns slightly negative at the top of the training range of $`R`$ (−0.0001 to −0.013 $`\pi / k`$ per GW, against a typical slope of about 0.04). More load would then lower the price. The effect is small, but it is a property of the form.
- **Exponential** fits as well and its slope $`\beta e^{\gamma R}`$ cannot change sign. With the fitted $`\beta > 0`$, the price rises with load everywhere. It is smooth, so its slope is defined at every $`R`$.

## Families disagree where batteries discharge

Weighted mean slope where the fleet charges and discharges, fuel-adjusted target, £/MWh per GW (`fleet_slopes.png`, and the table in `comparison.md`):

| Family | Charging, 2021–2024 | Discharging, 2021–2024 |
| --- | --- | --- |
| Cubic | 5.8, 11.0, 4.2, 2.8 | 13.9, 22.7, 10.2, 7.7 |
| Signed quadratic | 7.5, 12.0, 5.4, 3.9 | 11.8, 17.7, 8.8, 6.8 |
| Cubic with offset | 4.6, 5.9, 3.8, 3.1 | 3.8, 4.4, 3.4, 2.6 |
| Exponential | 5.1, 6.4, 4.6, 3.8 | 3.4, 3.9, 3.4, 2.7 |
| Isotonic | 5.1, 6.3, 5.1, 4.8 | 3.9, 5.9, 3.7, 2.8 |

The three families that fit agree within about 1.7 £/MWh per GW in charging hours. The cubic and signed quadratic are steeper, by up to double in 2022, and in discharging hours they are two to six times steeper than the rest. They fit badly, so they are not plausible central estimates. They stay in as robustness models because they bracket the steep end: they show how much the results depend on the curve being steep at high $`R`$. Because the families disagree this much, later results are reported for more than one family.

## Robustness models

- **`fuel_adjusted/cubic_offset`, `fuel_adjusted/isotonic`**: fit as well as the main model. They check that results do not depend on the exponential form.
- **`fuel_adjusted/signed_quadratic`, `fuel_adjusted/cubic`**: fit badly and are much steeper where the fleet operates. They give an upper bracket on the price response.
- **`raw_per_year/exponential`**: no fuel adjustment, one curve per year. It checks that results do not depend on dividing by $`k`$.

## What it gives up

- The exponential's slope is either rising or falling over all of $`R`$; it cannot be flat in the middle and steep at both ends. In the fuel-adjusted fits $`\gamma < 0`$, so the slope falls with $`R`$, and the curve misses the sharp rise above about 35 GW that the isotonic fit follows (`fits.png`). Few slots and little of the fleet's energy lie there (`slopes.png`).
- Both choices inherit the constant-σ noise model of [ADR-0003](0003-noise-model.md).
