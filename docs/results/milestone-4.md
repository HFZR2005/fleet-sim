# Transformer overloads and penetration

Eight homes, region C, 5–11 January 2026. Master seed 1, 30 replications. Four transformers, ADMD 2 kW, headroom 1.0, power factor 0.95, standard ratings [25, 50, 100] kVA. Each number below is the mean of those 30 replications, and the range in brackets is the 95% t-interval. A replication draws one fleet and the reported metric is the mean of that fleet over the seven days.

`scenarios/network-sweep.toml` is the diverse fleet at 0, 10, 25, 50, 75, and 100% on a four-transformer tree with no clustering (ρ = 0). The same file with `rho = 0.8` gives the clustered comparison. `scenarios/network.toml` is the single-penetration variant. The machine-readable intervals are in `docs/results/milestone-4.json`.

Demand is the first 100 households in the Low Carbon London file, in file order. See `docs/results/milestone-3.md` for notes on the demand source.

## Overload metrics against penetration (ρ = 0)

| Penetration | Overloaded share | Mean utilisation | Overload energy (kWh) | Hidden share |
| --- | --- | --- | --- | --- |
| 0% | — | — | — | — |
| 10% | — | — | — | — |
| 25% | — | — | — | — |
| 50% | — | — | — | — |
| 75% | — | — | — | — |
| 100% | — | — | — | — |

## Where overloads first appear

For each replication, the overload crossing is the smallest penetration on the grid where the share of transformers overloaded is above zero.

Without clustering (ρ = 0): —

With clustering (ρ = 0.8): —

The first grid level whose 95% interval for the overloaded share lies wholly above zero is — without clustering and — with clustering.

## Hidden-overload share

The hidden-overload share is the fraction of slots where the fleet total stays within the sum of all transformer limits but at least one transformer exceeds its own. At low penetration it is —. At full penetration it is —. This is the number that shows why fleet totals alone mislead.

## With vs without batteries

At each penetration, the "without batteries" pass runs the same homes, topology, and seed at penetration 0 (no batteries). The paired difference isolates the battery effect on overloads.

| Penetration | Overloaded share (paired Δ) | Overload energy (paired Δ, kWh) |
| --- | --- | --- |
| 0% | 0 | 0 |
| 10% | — | — |
| 25% | — | — |
| 50% | — | — |
| 75% | — | — |
| 100% | — | — |

## Clustered vs unclustered

With ρ = 0.8, battery ownership clusters on transformers: homes on the same transformer tend to all adopt or all skip. This concentrates charging load and should make overloads worse at the same penetration.

Results pending: run `scenarios/network-sweep.toml` with `rho = 0.8` and compare with the ρ = 0 table above.
