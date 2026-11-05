---
covers:
  - data/agile.py
  - models/network.py
---

# UK energy context

This page introduces the UK energy concepts the simulator builds on. Each section is a brief explanation with links to authoritative sources. See [Assumptions](assumptions.md) for the specific modelling choices fleet-sim makes.

## The Agile tariff

[Octopus Agile](https://octopus.energy/smart/agile/) is a domestic electricity tariff whose import price changes every half hour. Prices are published the evening before, based on day-ahead wholesale markets. They are cheapest overnight (often 5–15 p/kWh) and highest in the early evening peak (sometimes 30–50 p/kWh, occasionally negative). A home battery that charges during cheap slots and discharges during expensive ones can reduce the bill. The simulator uses the [Octopus Energy API](https://developer.octopus.energy/docs/api/) to fetch historical half-hourly prices.

## The distribution network

Electricity reaches UK homes through a hierarchy of transformers. Power flows from the transmission grid (400/275 kV) through a **Grid Supply Point** (GSP), down through primary substations (33 kV → 11 kV) and then secondary substations (11 kV → 400 V) to the low-voltage feeders that serve homes. Each secondary substation has a transformer with a fixed power rating.

The simulator models the last mile: a tree of secondary transformers, each serving a group of homes. When many homes on the same transformer charge batteries at the same time, the combined flow can exceed the transformer's rating — an **overload**. The [Energy Networks Association](https://www.energynetworks.org/) publishes standards and guidance on network capacity.

## DNO regions

Great Britain is divided into 14 electricity distribution regions, each operated by a Distribution Network Operator (DNO). Octopus Agile prices vary by region because each GSP group sees different wholesale costs. The simulator identifies regions by their single-letter GSP code (e.g., `C` for South Wales). The [Octopus region page](https://octopus.energy/dashboard/new-quote/smart/tariffs/) shows which code corresponds to which area.

## Transformer ratings

A secondary distribution transformer is rated in **kVA** (kilovolt-amperes). Common UK residential ratings are 25, 50, and 100 kVA. The active power it can deliver depends on the **power factor** — the ratio of real power (kW) to apparent power (kVA). At a power factor of 0.95, a 50 kVA transformer delivers up to 47.5 kW.

Transformers are sized using **ADMD** (After Diversity Maximum Demand) — the expected peak demand per home once diversity between households is accounted for. The design load is `n_homes × ADMD × headroom`, rounded up to the nearest standard rating. In practice, diversity means not all homes peak simultaneously, so transformers are not sized for the sum of individual peaks. See [Assumptions — Transformer sizing](assumptions.md) for the values the simulator uses.

## Battery products

Typical UK home batteries range from 5 kWh to 13.5 kWh of usable storage. Charge and discharge rates are usually 3.6–5.0 kW. Round-trip efficiency (energy out ÷ energy in) is around 90–97%. The simulator draws each home's battery from a configurable catalogue of products — see [Assumptions](assumptions.md) for the default distribution.

## Key terms

| Term | Definition |
| --- | --- |
| **Slot** | One half-hour period. A day has 48 slots. |
| **Penetration** | The fraction of homes that own a battery, from 0 (none) to 1 (all). |
| **Coincidence factor** | Fleet peak ÷ sum of individual peaks. Rises toward 1 as homes charge in sync. |
| **Peak-to-average ratio** | Peak demand ÷ mean demand over the day. Higher means more peaky. |
| **Utilisation** | Peak flow through a transformer ÷ its rated limit. Above 1 means overloaded. |
| **Overload** | The power (kW) by which flow exceeds the transformer's limit in a slot. |
| **Hidden overload** | A slot where the fleet total is within the sum of all limits, but at least one transformer exceeds its own. Fleet-level monitoring would miss it. |
| **Replication** | One independent run of the whole experiment, from a distinct random seed. Intervals are computed across replications. |
| **ADMD** | After Diversity Maximum Demand — the expected peak per home once diversity is accounted for. |
