---
covers:
  - calibration/price_curves.toml
---

# Price data from May 2021

The price-curve data starts on 1 May 2021, when the UK ETS began trading. The training years are 2021 to 2024 and the final-test year is 2025.

Before May 2021 the carbon price is the EU ETS price. No free, licence-clear sterling source for it was found (`docs/data/fuel-cost.md`), so 2019, 2020 and January to April 2021 have no fuel cost k and every slot in them would be dropped.

2021 is a part year: May to December, with about a third of its slots capped. It stays in, because it is the only data on the way into the 2022 gas crisis, and leave-one-year-out works on a part year, with a smaller fold.

What this gives up: the cheap-gas years, so the fuel-adjusted curve is not tested at k below about £45/MWh; the 2020 low-demand year; and two folds. If an EU ETS series is added later, 2019 and 2020 come back by changing the config alone.
