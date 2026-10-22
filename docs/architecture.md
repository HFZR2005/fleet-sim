# Architecture

A run draws a fleet, solves each home on its own, and reads the network off the resulting imports. A home never reads a node. The only signal it can receive from the network is the per-slot price adjustment, which milestone 4 leaves at zero. The limit is measured here and enforced later, through that price.

## Stages

1. **Fleet.** `generate_fleet` draws households and batteries for one replication seed. `with_demand` reloads each home on the civil day being solved.
2. **Topology.** `build_topology` turns the scenario's `[network]` section into a `NetworkSpec`: a root, one node per transformer, and a map from `home_id` to its transformer. This stage is a stub. It splits the homes into equal groups, gives every transformer the scenario's `limit_kw`, and sets no locations. Sizing, standard ratings, and the bounding box are stored on `NetworkSettings` and ignored.
3. **Assignment.** `assign_transformers` writes `transformer_id` onto each home from that map.
4. **Day.** `solve_fleet` schedules every home. `Network.evaluate` then aggregates imports. Without a spec it reports the root only. With a spec it sums each transformer from its homes and the root from the transformers. Overloads on that path are a stub: always zero, including when the flow is above `limit_kw`.
5. **Overload.** `day_overload` is a stub and returns zeros. `summarise_replication` reduces those days, and the replication means go through the same t-interval as any other metric.
6. **Report and figure.** The command prints the intervals with a `STUB` prefix and lists the stubs it called. `plot_network_overload` draws them with a `STUB` watermark. `--release` stops before writing outputs when any stub ran.

## Types

| Type | Role |
| --- | --- |
| `NetworkSettings` | The `[network]` section: how many transformers, the stub limit, and the sizing, location, and clustering fields later issues read |
| `NetworkNode` | `node_id`, `parent_id` (`None` at the root), optional `limit_kw`, optional `Location` |
| `NetworkSpec` | The tree, plus `home_transformer` |
| `NodeFeedback` | One node's flow, limit, and overload for the day |
| `DayOverload` | Per transformer: peak utilisation, overload energy (kWh), overloaded slots; plus the hidden-overload share |
| `ReplicationOverload` | Share of transformers overloaded, mean and worst utilisation, total overload energy, the hour overloads occur most, hidden-overload share |

A scenario with no `[network]` section does not enter this path. It still solves against one unconstrained root.
