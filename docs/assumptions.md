---
covers:
  - models/scenario.py
  - models/network.py
  - fleet/topology.py
  - fleet/generate.py
  - data/agile.py
---

# Assumptions

Choices a reader will want to question. Each one is a modelling decision, and the source of the numbers is named with it.

## Battery products

A home that owns a battery is given a product, not three independent numbers. The capacity is one of three usable sizes. The inverter rating is then drawn from the ratings that size is sold with, and charge and discharge both take that rating.

| Usable capacity | Inverter ratings | Weight |
| --- | --- | --- |
| 5 kWh | 3.6 kW | 1 |
| 10 kWh | 3.6 kW or 5 kW | 1 |
| 13.5 kWh | 5 kW | 1 |

The weights are equal. This is not a sales mix. The project does not have an installation census to weight the sizes by, so each size is equally likely and the table says so.

5 kWh is the small usable size and 10 kWh is the mid size. 3.6 kW is the inverter rating sold under the 3.68 kW G98 single-phase limit (16 A). 5 kW is the continuous charge and discharge rating of a Tesla Powerwall 2, and that battery's usable capacity is 13.5 kWh, the large size in the table. 5 kW is also one of the ratings paired with 10 kWh, for a connection above that G98 limit.

The starting state of charge is 0.5 for every battery. It is the value in `home.toml`. It is not a product attribute, so it is not drawn.

## Efficiency

Charge efficiency and discharge efficiency are drawn separately from the same truncated normal: mean 0.95, standard deviation 0.01, kept inside [0.92, 0.97]. The mean is the one-way efficiency in `home.toml`. A round trip at that mean keeps 0.9025 of the energy, which is the neighbourhood of a 90% round-trip lithium home battery. The truncation is there so a draw cannot leave the band those inverters actually sit in, and so it stays inside the fraction the battery model accepts.

## Who owns a battery

Penetration `p` gives a battery to `floor(p * N + 0.5)` homes, halfway cases rounding away from zero. One uniform number is drawn for each home from the `penetration` stream. The homes with the smallest draws own the batteries, and a tie goes to the lower home index. A lower penetration is then a subset of a higher one for the same seed: the 25% owners are among the 50% owners. Drawing each home independently would not hit that count.

The draw does not look at the home's demand. A household is assigned from the `demand` stream and a product from the `battery` stream, and neither draw is conditioned on the other. Real ownership may well follow the house, the income, or the size of the load. That coupling is a possible refinement. It is not in this generator.

## Clustered ownership

Neighbours tend to adopt batteries together: word of mouth, the same installer, the same street. The scenario parameter ρ (`rho`, in [0, 1]) controls how much ownership clusters by transformer.

Each home's ownership score mixes two components:

    score = ρ × transformer_draw + (1 − ρ) × individual_draw

The individual draw is the home's own uniform number from the `penetration` stream (the same draw as in the unclustered case). The transformer draw is one uniform number per transformer, drawn from the `ownership-cluster` stream and shared by every home on that transformer.

Homes are ranked by score. At penetration p, the top `round(p × N)` homes own batteries. This preserves exact counts and nesting for any ρ.

With ρ = 0, the score equals the individual draw, so ownership is identical to the unclustered case for the same seed. With ρ = 1, all homes on a transformer share the same score, so they all adopt or all do not: penetration varies sharply between transformers. Intermediate ρ gives partial clustering.

ρ is a modelling choice, not a measured value. There is no UK dataset that calibrates how much battery adoption clusters at the transformer level. Setting ρ to zero recovers the uniform case; setting it higher explores how clustering amplifies transformer stress.

## Identical homes

Identical mode builds the diverse fleet, then replaces it with N copies of the mean home. Demand in each slot is the mean of the diverse homes' demand. The battery is the mean of the batteries the diverse fleet actually owns. If none own one, the copies have none. If some own one, every copy gets that mean battery, so the homes are actually identical. A diversity comparison that should keep the same number of batteries wants a penetration of 1, where every diverse home already has one.

## Demand

Demand is a day from the Low Carbon London pool, documented in `docs/household-demand.md`. Energy in the file is kWh per half hour. The home stores average kW, which is that energy divided by 0.5 hours. The trial predates widespread heat pumps and electric vehicles.

## Transformer sizing

A distribution transformer serves a group of homes. Its rating is chosen so that the peak demand of all connected homes, as seen at the transformer, stays within that rating. The design uses after-diversity maximum demand.

**ADMD** (after-diversity maximum demand) is the expected peak demand per connected home once the diversity of usage patterns is taken into account. A single home may peak at 10 kW, but twenty homes on the same transformer are unlikely to all peak at once. ADMD is the average peak each home contributes to the transformer's total peak. UK distribution network operators use ADMD tables that depend on the number of homes and the dwelling type; see ACE Report 49 and the ENA Engineering Recommendation P2/8.

The design load of a transformer is the number of homes it serves multiplied by the ADMD, multiplied by a headroom factor:

    design_kw = n_homes × admd_kw × headroom

That load is then converted to kVA by dividing by the power factor and rounded up to the nearest standard transformer rating:

    required_kva = design_kw / power_factor
    selected_kva = smallest standard rating ≥ required_kva
    limit_kw = selected_kva × power_factor

The default ADMD is a scenario parameter (`admd_kw`), not a table. The default headroom is 1.0 and the default power factor is 0.95, which is typical for UK domestic loads. The standard ratings default to 25, 50, 100 kVA. All of these are modelling choices and can be overridden in the scenario file.

When the design load exceeds the largest available rating the largest rating is used. This is the point of the study: batteries can push a transformer above the rating it was sized for.

## Home assignment

Each home is assigned to a uniformly random transformer. The number of transformers is set in the scenario. The random assignment means some transformers serve more homes than others, and their limits vary accordingly. The assignment uses the `"topology"` random stream so it is reproducible from the seed.

## Transformer locations

Each transformer is given a synthetic location: a random point within a bounding box set in the scenario (defaults to a rectangle covering London). These are for the map in a later milestone and have no effect on the simulation.

## Transformer limits

A limit is a fixed kW cap on a node's flow in each half-hour slot. The same number applies in every slot. A real distribution transformer has a cyclic rating and can carry more than its nameplate for a short time, so an overload here means the flow exceeds the rating. It does not mean the transformer fails.
