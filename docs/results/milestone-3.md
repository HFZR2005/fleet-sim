# Diversity and penetration

Eight homes, region C, 5–11 January 2026. Master seed 1, 30 replications. Each number below is the mean of those 30 replications, and the range in brackets is the 95% t-interval. A replication draws one fleet and the reported metric is the mean of that fleet over the seven days.

`scenarios/diverse.toml` is the diverse fleet at full penetration. `scenarios/identical.toml` is the paired identical fleet: same seed, dates, size, and battery catalogue, with every home a copy of the mean. `scenarios/penetration-sweep.toml` is the diverse fleet at 0, 10, 25, 50, 75, and 100%. The machine-readable intervals are in `docs/results/milestone-3.json`.

Demand is the first 100 households in the Low Carbon London file, in file order, not a random sample of all 5,567. The trial is 2011–2014, before heat pumps and electric vehicles were common, so these shapes understate winter peaks from those loads.

## Diversity

At full penetration the diverse fleet peaks at 36.83 kW (35.72 to 37.93). The identical fleet peaks higher. The paired difference, diverse minus identical, is −3.57 kW (−4.34 to −2.80). The peak-to-average ratio is 0.61 lower (−0.76 to −0.47), and the coincidence factor is 0.089 lower (−0.104 to −0.073).

Identical homes are copies, so they charge in the same half-hours and their coincidence is 1. Diverse homes keep their own demand shape and their own battery, so the charges do not line up exactly and the fleet peak is lower. All three intervals lie entirely below zero.

## Penetration

Of eight homes, 10% is one battery, 25% is two, 50% is four, 75% is six, and 100% is eight.

| Penetration | Peak (kW) | Peak-to-average | Coincidence | Peak minus no battery (kW) |
| --- | --- | --- | --- | --- |
| 0% | 10.64 (9.53 to 11.75) | 2.16 (2.09 to 2.24) | 0.58 (0.56 to 0.61) | 0 |
| 10% | 11.01 (9.98 to 12.04) | 2.25 (2.16 to 2.35) | 0.53 (0.51 to 0.55) | 0.37 (0.09 to 0.65) |
| 25% | 13.60 (12.78 to 14.41) | 2.84 (2.63 to 3.05) | 0.58 (0.57 to 0.60) | 2.96 (2.28 to 3.64) |
| 50% | 21.14 (20.32 to 21.96) | 4.45 (4.04 to 4.85) | 0.73 (0.71 to 0.74) | 10.50 (9.45 to 11.56) |
| 75% | 29.12 (28.09 to 30.15) | 6.07 (5.51 to 6.64) | 0.83 (0.81 to 0.85) | 18.48 (17.20 to 19.76) |
| 100% | 36.83 (35.72 to 37.93) | 7.61 (6.89 to 8.34) | 0.91 (0.90 to 0.93) | 26.19 (24.76 to 27.61) |

With no batteries the fleet peaks at about 11 kW. One battery is already enough for the mean peak to rise, and that interval sits above zero. By the time every home has a battery the peak is about 27 kW higher than the same homes with no battery. The homes are also more coincident: batteries answering the same prices line up, which is the opposite of the diversity effect above.

## Where the battery peak first exceeds the no-battery peak

For each replication, the crossing is the smallest penetration on the grid where the with-battery peak exceeds the no-battery peak by more than 0.001 kW. It was 10% in 19 of the 30 replications, 25% in 10, and 50% in 1. None stayed at or below the no-battery peak through 100%. The crossings run from 10% to 50%.

The first grid level whose 95% interval for the peak difference lies wholly above zero is 10%. That is one battery in this fleet of eight.
