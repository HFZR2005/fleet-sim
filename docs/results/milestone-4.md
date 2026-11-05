---
covers:
  - commands/network.py
  - fleet/topology.py
  - fleet/overload.py
  - fleet/network.py
  - viz/network.py
---

# Transformer overloads and penetration

Fifty homes, region C, 5–11 January 2026. Master seed 1, 30 replications. Four transformers, ADMD 2 kW, headroom 1.0, power factor 0.95, standard ratings [25, 50, 100] kVA. Each number below is the mean of those 30 replications, and the range in brackets is the 95% t-interval. A replication draws one fleet and the reported metric is the mean of that fleet over the seven days.

`scenarios/network-sweep.toml` is the diverse fleet at 0, 10, 25, 50, 75, and 100% on a four-transformer tree with no clustering (ρ = 0). The same file with `rho = 0.8` gives the clustered comparison. `scenarios/network.toml` is the single-penetration variant. The machine-readable intervals are in `docs/results/milestone-4.json`.

Demand is the first 100 households in the Low Carbon London file, in file order. See `docs/results/milestone-3.md` for notes on the demand source.

## Overload metrics against penetration (ρ = 0)

| Penetration | Overloaded share | Mean utilisation | Overload energy (kWh) | Hidden share |
| --- | --- | --- | --- | --- |
| 0% | 0.00 (0.00 to 0.00) | 0.43 (0.42 to 0.45) | 0.00 (0.00 to 0.00) | 0.00 (0.00 to 0.00) |
| 10% | 0.01 (−0.01 to 0.03) | 0.46 (0.44 to 0.48) | 0.02 (−0.02 to 0.07) | 0.00 (−0.00 to 0.00) |
| 25% | 0.15 (0.09 to 0.21) | 0.60 (0.59 to 0.62) | 3.08 (1.18 to 4.97) | 0.01 (0.00 to 0.01) |
| 50% | 0.53 (0.45 to 0.60) | 0.93 (0.91 to 0.95) | 40.53 (28.70 to 52.37) | 0.04 (0.03 to 0.05) |
| 75% | 0.99 (0.97 to 1.01) | 1.30 (1.28 to 1.32) | 210.79 (186.55 to 235.03) | 0.03 (0.03 to 0.03) |
| 100% | 1.00 (1.00 to 1.00) | 1.66 (1.64 to 1.68) | 548.75 (517.03 to 580.48) | 0.02 (0.02 to 0.03) |

Without batteries there are zero overloads at any penetration. The baseline utilisation is 0.43 at 0%, reflecting demand alone.

## Where overloads first appear

For each replication, the overload crossing is the smallest penetration on the grid where the share of transformers overloaded is above zero.

Without clustering (ρ = 0): the crossing was at 25% in 15 of 30 replications, 50% in 14, and 10% in 1. The crossings run from 10% to 50%. The first grid level whose 95% interval for the overloaded share lies wholly above zero is 25%.

With clustering (ρ = 0.8): the crossing was at 10% in 14 replications, 25% in 14, and 50% in 2. The crossings run from 10% to 50%. The first grid level whose 95% interval for the overloaded share lies wholly above zero is 10%. Clustering brings overloads forward: when battery owners cluster on the same transformer, that transformer sees concentrated charging load at lower penetrations.

## Hidden-overload share

The hidden-overload share is the fraction of slots where the fleet total stays within the sum of all transformer limits but at least one transformer exceeds its own. Without clustering it peaks at 0.04 (0.03 to 0.05) at 50% penetration: enough batteries to overload some transformers but not enough to push the fleet total over the aggregate limit. By 100% the fleet total is also over, so the hidden share falls to 0.02. With clustering the peak is higher: 0.07 (0.06 to 0.07) at 50%.

## With vs without batteries

At each penetration, the "without batteries" pass runs the same homes, topology, and seed at penetration 0 (no batteries). The paired difference isolates the battery effect on overloads. Without batteries there are zero overloads, so the entire overloaded share and overload energy is the battery effect.

| Penetration | Overloaded share (paired Δ) | Overload energy (paired Δ, kWh) |
| --- | --- | --- |
| 0% | 0.00 (0.00 to 0.00) | 0.00 (0.00 to 0.00) |
| 10% | 0.01 (−0.01 to 0.03) | 0.02 (−0.02 to 0.07) |
| 25% | 0.15 (0.09 to 0.21) | 3.08 (1.18 to 4.97) |
| 50% | 0.53 (0.45 to 0.60) | 40.53 (28.70 to 52.37) |
| 75% | 0.99 (0.97 to 1.01) | 210.79 (186.55 to 235.03) |
| 100% | 1.00 (1.00 to 1.00) | 548.75 (517.03 to 580.48) |

The battery effect on overloads is the entire signal: these transformers are not stressed by demand alone. Every kWh of overload energy comes from batteries charging during cheap half-hours.

## Clustered vs unclustered

With ρ = 0.8, battery ownership clusters on transformers: homes on the same transformer tend to all adopt or all skip.

| Penetration | Overloaded share (ρ = 0) | Overloaded share (ρ = 0.8) | Overload energy (ρ = 0) | Overload energy (ρ = 0.8) |
| --- | --- | --- | --- | --- |
| 0% | 0.00 | 0.00 | 0.00 | 0.00 |
| 10% | 0.01 | 0.12 (0.07 to 0.16) | 0.02 | 2.32 (0.80 to 3.84) |
| 25% | 0.15 | 0.26 (0.22 to 0.30) | 3.08 | 69.68 (49.89 to 89.48) |
| 50% | 0.53 | 0.53 (0.49 to 0.58) | 40.53 | 197.22 (161.30 to 233.14) |
| 75% | 0.99 | 0.76 (0.72 to 0.80) | 210.79 | 332.13 (298.59 to 365.67) |
| 100% | 1.00 | 1.00 | 548.75 | 548.75 |

At 10% penetration clustering raises overload energy from near zero to 2.32 kWh: five batteries on one transformer instead of spread across four. At 25% the effect is dramatic: 69.68 kWh clustered versus 3.08 unclustered. At 50% the overloaded shares are similar (0.53 vs 0.53) but the energy is nearly five times higher clustered (197 vs 41 kWh), because the transformers that do overload are loaded much more heavily. At 75% the pattern inverts for the share: clustering leaves one or two transformers with no batteries at all, so fewer are overloaded (0.76 vs 0.99), but the ones that are overloaded carry even more energy (332 vs 211 kWh). At 100% both converge: every home has a battery regardless.
