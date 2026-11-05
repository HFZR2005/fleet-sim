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
