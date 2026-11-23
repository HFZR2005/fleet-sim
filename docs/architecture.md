---
covers:
  - commands/network.py
  - commands/market.py
  - fleet/market.py
  - models/market.py
  - viz/market.py
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

## Fleet in the loop

A scenario with a `[market]` section makes each home's tariff depend on what the whole fleet charges, through the price curve (`docs/formulation.md`, Fleet in the loop). It needs a `[network]` section too, and takes precedence over the plain network path. `commands/market.py` runs it.

### Stages

1. **Fleet and topology.** As in the network path: `build_topology` once, then `generate_fleet` and `assign_transformers` for each replication, national fleet size M and local penetration.
2. **Price inputs.** `day_price_inputs` builds a `DayPriceInputs` for each day: residual load R, fuel cost k and wholesale price π per slot, and the historical Agile rates. Its `prices(added_load_gw)` method is (PRICE): the Agile rate in each slot when the fleet adds b GW.
3. **Equilibrium.** `solve_market_day` solves the fleet-day as one linear program, (JOINT) subject to (LINK), and returns a `MarketDay`: the added load b*, the prices P(b*), and each home's schedule under two allocations. **Joint** is the LP's own schedule. **Re-planned** is each home solved alone at P(b*). It also returns `EquilibriumDiagnostics`.
4. **Network.** `Network.evaluate` runs once per allocation per day, then `day_overload` and `summarise_replication` produce milestone-4 overload metrics for each allocation.
5. **Metrics and report.** `market_metrics` reduces a replication's days to `MarketMetrics`. Replications go through `t_interval` into one `MarketLevelResult` per (M, penetration), and diagnostics keep their worst value. The command writes `frames.json` (joint allocation, first replication, last point), `metadata.json`, `metrics.json` and the market figure. `--release` stops before writing when any stub ran.

### Types

| Type | Role |
| --- | --- |
| `MarketSettings` | The `[market]` section: M (one value or a list), price model name and parameters file, segments K, equilibrium tolerance (pence per home per day), the curve's range of R + b |
| `DayPriceInputs` | One UK day in one region: R, k, π (with censoring bounds) per slot, the historical rates, and `prices(b) -> PriceSeries` |
| `MarketDay` | b* per slot (GW), P(b*), every home's schedule under the joint and re-planned allocations, and the diagnostics |
| `EquilibriumDiagnostics` | Linearisation error (p/kWh), (MODE) breaks, largest and total re-plan saving (pence), slots with R + b outside the curve's range |
| `MarketMetrics` | Per replication: peak added load and its hour, saving per battery home, price change for homes without a battery, mean charging and discharging price |
| `MarketLevelResult` | One (M, penetration) point: market metrics and both allocations' overload metrics as intervals, and the worst diagnostics |

## Price curves

A separate pipeline calibrates price curves: the relationship between wholesale electricity price and residual load (demand minus renewables). The curve tells the fleet simulator how scheduling decisions that shift aggregate demand change the price. It runs from `scripts/fit_price_curves.py`, not through the `fleet-sim` CLI.

### Stages

1. **Load.** Three data loaders in `fleet_sim/data/` provide wholesale prices (inverted from Agile), residual load, and marginal fuel cost. `build_dataset` in `prices/dataset.py` joins them on settlement period into `PriceObservation` records. It drops slots missing any input, and records per year how many each rule dropped. A slot whose Agile rate is capped is kept as a censored observation: its π is a lower bound, with an upper bound where one is known (the Q4 2022 EPG floor). `summarise` gives rows, censored rows, and the mean and range of π (exact slots only), R and k per year. Censored slots stay in: fitting uses their bounds, and evaluation leaves them out of every error.
2. **Split.** Splits are by whole year, because neighbouring half-hours are near-duplicates. `selection_folds` makes the leave-one-year-out folds for model selection, over the training years only. `final_test_split` is the only function that returns final-test rows; `compare` never calls it.
3. **Transform.** A `Target` extracts the dependent variable from each observation. Raw targets use the wholesale price directly; the fuel-adjusted target divides it by fuel cost. A target also says whether to fit per year or pool all years.
4. **Fit.** A `PriceCurve` fits residual load and bounds on `y` and returns a `FittedCurve` with `predict` and `slope` methods. No family knows about targets.
5. **Evaluate.** `evaluate` scores a fitted curve on one year, producing a `FitResult`: RMSE overall, by season and by hour, the slope error between consecutive half-hours, and that slope error weighted by where a fleet charges and discharges. The weights come from `fleet_charging` in `prices/fleet_weights.py`, which runs the `[evaluation]` scenario over the training years at the Agile prices of those days (`HistoricalAgileSource`) and caches the run. Pooled targets are scored on each held-out year. Per-year targets are fitted to each year and scored on the same year, since a one-year curve has no other year to predict.
6. **Compare / Finalise** (`prices/pipeline.py`; the script loads the data and the fleet's charging, then calls it). `compare` runs all (family, target) models and writes `evaluation.json`, the Markdown table from `comparison_table`, figures, and residuals for the models named on the command line. `finalise` refits the `[chosen]` main and robustness models on training data, evaluates them on the final-test year, and writes `calibration/price_curves.json` — but only after `require_no_stubs()` confirms no stub ran, and only if that file does not exist yet, so the final-test year is read once. Later milestones read a model back with `load_price_model`.

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
| `PriceCurve` | Protocol: `fit(r_gw, y_lower, y_upper) -> FittedCurve` |
| `Target` | Protocol: `to_target(obs) -> y`, `to_price(y, obs) -> price`, `per_year` flag |
| `FitResult` | Metrics for one model on one year |
| `FleetCharging` | A fleet's net battery power in each slot, for weighting slope errors |
| `EvaluationReport` | Comparison of all fitted models |
| `CalibrationConfig` | Validates `calibration/price_curves.toml` |
