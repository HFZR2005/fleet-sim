# Frame file

A fleet run writes one JSON file. Each element of `frames` is one half-hour slot. `schema_version` is `1`.

A frame has:

- `slot_start`: the start of the slot, as a UTC timestamp
- `price_p_per_kwh`: the import tariff in that slot, in pence per kWh
- `homes`: one object per home
- `nodes`: one object per network node. Milestone 2 has a single root node

A home object has:

- `home_id`
- `transformer_id`, or `null` when the home is not under a named transformer
- `soc`: state of charge at the end of the slot, a fraction from 0 to 1
- `mode`: `charging`, `discharging`, or `idle`
- `import_kw`: scheduled grid import, in kW
- `demand_kw`: the home's demand in kW, which is the import there would have been with no battery

A node object has:

- `node_id`
- `flow_kw`: power through the node in that slot, in kW
- `limit_kw`: the node's limit in kW, or `null` when it has none
- `overload_kw`: how far the flow sits above the limit. It is zero when there is no limit

`mode` comes from the schedule's charge and discharge power. A positive charge is `charging`, a positive discharge is `discharging`, and neither is `idle`.

A scenario run also writes `metadata` on this file: the scenario, the master seed, the package version, and the git commit. The same record is written to `metadata.json` beside the frames. A frame file from `run-fleet` leaves `metadata` out.
