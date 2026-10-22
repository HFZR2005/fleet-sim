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

## Identical homes

Identical mode builds the diverse fleet, then replaces it with N copies of the mean home. Demand in each slot is the mean of the diverse homes' demand. The battery is the mean of the batteries the diverse fleet actually owns. If none own one, the copies have none. If some own one, every copy gets that mean battery, so the homes are actually identical. A diversity comparison that should keep the same number of batteries wants a penetration of 1, where every diverse home already has one.

## Demand

Demand is a day from the Low Carbon London pool, documented in `docs/household-demand.md`. Energy in the file is kWh per half hour. The home stores average kW, which is that energy divided by 0.5 hours. The trial predates widespread heat pumps and electric vehicles.
