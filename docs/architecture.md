---
covers:
  - commands/network.py
  - fleet/generate.py
  - fleet/topology.py
  - fleet/network.py
  - fleet/overload.py
  - fleet/solve.py
  - viz/network.py
  - models/network.py
  - models/results.py
  - prices/config.py
  - prices/dataset.py
  - prices/curves.py
  - prices/targets.py
  - prices/evaluation.py
  - prices/response.py
  - prices/figures.py
  - data/agile_formula.py
  - data/agile_history.py
  - data/wholesale.py
  - data/residual_load.py
  - data/gas_price.py
  - data/carbon_price.py
  - data/fuel_cost.py
---

# Architecture

A run draws a fleet, solves each home on its own, and reads the network off the resulting imports. A home never reads a node. The only signal it can receive from the network is the per-slot price adjustment, which milestone 4 leaves at zero. The limit is measured here and enforced later, through that price.

## Stages

1. **Fleet.** `generate_fleet` draws households and batteries for one replication seed. `with_demand` reloads each home on the civil day being solved.
2. **Topology.** `build_topology` turns the scenario's `[network]` section into a `NetworkSpec`: a root, one node per transformer, and a map from `home_id` to its transformer. Each transformer's limit is sized from ADMD, headroom, power factor, and the nearest standard rating. When clustering is enabled (ρ > 0), battery ownership clusters by transformer.
3. **Assignment.** `assign_transformers` writes `transformer_id` onto each home from that map.
4. **Day.** `solve_fleet` schedules every home. `Network.evaluate` then aggregates imports. Without a spec it reports the root only. With a spec it sums each node from the leaves upward: the homes attached to the node, then each child into its parent. Overload is how far the flow sits above the limit, and a node with no limit stays at zero.
5. **Overload.** `day_overload` computes per-transformer overload metrics for one day: peak utilisation, overload energy, overloaded slot count, and the hidden-overload share. `summarise_replication` reduces those days, and the replication means go through the same t-interval as any other metric.
6. **Report and figures.** The command prints the intervals and saves three figures: the overloaded-share curve against penetration, one transformer's daily flow against its limit, and the peak-utilisation distribution across transformers. `--release` stops before writing outputs when any stub ran.

## Types

| Type | Role |
| --- | --- |
| `NetworkSettings` | The `[network]` section: transformer count, ADMD, headroom, power factor, standard ratings, clustering ρ, and the bounding box |
| `NetworkNode` | `node_id`, `parent_id` (`None` at the root), optional `limit_kw`, optional `Location` |
| `NetworkSpec` | The tree, plus `home_transformer` |
| `NodeFeedback` | One node's flow, limit, and overload for the day |
| `DayOverload` | Per transformer: peak utilisation, overload energy (kWh), overloaded slots; plus the hidden-overload share |
| `ReplicationOverload` | Share of transformers overloaded, mean and worst utilisation, total overload energy, the hour overloads occur most, hidden-overload share |

A scenario with no `[network]` section does not enter this path. It still solves against one unconstrained root.

## Price curves

A separate pipeline calibrates price curves: the relationship between wholesale electricity price and residual load (demand minus renewables). The curve tells the fleet simulator how scheduling decisions that shift aggregate demand change the price. It runs from `scripts/fit_price_curves.py`, not through the `fleet-sim` CLI.

### Stages

1. **Load.** Three data loaders in `fleet_sim/data/` provide wholesale prices (inverted from Agile), residual load, and marginal fuel cost. `build_dataset` in `prices/dataset.py` joins them on settlement period into `PriceObservation` records. It drops slots missing any input, and records per year how many each rule dropped. A slot whose Agile rate is capped is kept as a censored observation: its π is a lower bound, with an upper bound where one is known (the Q4 2022 EPG floor). `summarise` gives rows, censored rows, and the mean and range of π (exact slots only), R and k per year. Fitting doesn't use bounds yet, so `exact_only` removes censored slots once, in `scripts/fit_price_curves.py`, before anything is fitted or evaluated.
2. **Split.** Splits are by whole year, because neighbouring half-hours are near-duplicates. `selection_folds` makes the leave-one-year-out folds for model selection, over the training years only. `final_test_split` is the only function that returns final-test rows; `compare` never calls it.
3. **Transform.** A `Target` extracts the dependent variable from each observation. Raw targets use the wholesale price directly; the fuel-adjusted target divides it by fuel cost. A target also says whether to fit per year or pool all years.
4. **Fit.** A `PriceCurve` fits `(residual_load, y)` data and returns a `FittedCurve` with `predict` and `slope` methods. No family knows about targets.
5. **Evaluate.** `evaluate` scores the fitted curve on held-out data, producing a `FitResult` with RMSE and R² metrics.
6. **Compare / Finalise.** `compare` runs all (family, target) models and writes a comparison table and figures. `finalise` refits the chosen model on training data, evaluates on the final-test year, and writes the parameters file — but only after `require_no_stubs()` confirms no stub ran.

A model is a (curve family, target) pair. The family does not know about targets, and no target knows about families.

### Types

| Type | Role |
| --- | --- |
| `PriceObservation` | One half-hour: timestamp, wholesale price (£/MWh), whether it is censored and its upper bound if known, residual load (GW), fuel cost (£/MWh), year |
| `PriceDataset` | Aligned observations, with the per-year drop and censored counts (`YearDrops`) that produced them |
| `SplitSpec` | `[splits]` config: training years and the final-test year, which must come after them |
| `Fold` | One leave-one-year-out split: held-out year, train and test datasets |
| `YearSummary` | Rows, censored rows, and the mean and range of π (exact slots only), R and k for one year |
| `FittedCurve` | Protocol: `predict(r_gw)` and `slope(r_gw)` |
| `PriceCurve` | Protocol: `fit(r_gw, y) -> FittedCurve` |
| `Target` | Protocol: `to_target(obs) -> y`, `to_price(y, obs) -> price`, `per_year` flag |
| `FitResult` | Metrics for one model on one split |
| `EvaluationReport` | Comparison of all fitted models |
| `CalibrationConfig` | Validates `calibration/price_curves.toml` |
