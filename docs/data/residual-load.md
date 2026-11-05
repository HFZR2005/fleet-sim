---
covers:
  - data/settlement.py
  - data/neso_demand.py
  - data/elexon_generation.py
  - data/residual_load.py
---

# Residual load

Half-hourly GB residual load R in GW, following Hirth's definition:
demand minus wind and solar, plus the daily mean of net exports and
pumped-storage consumption.

## Derivation

$$
R_t = \text{ND}_t - W^{\text{tx}}_t + \bar{F}_t
$$

| Symbol | Description | Source | Column(s) |
|--------|-------------|--------|-----------|
| ND | National Demand | NESO Historic Demand Data | `ND` |
| W^tx | Transmission-connected wind generation | Elexon FUELHH (fuel type = WIND) | `generation` |
| F̄ | Daily mean flexibility adjustment | Computed from NESO columns | see below |

### Why ND, not underlying demand

ND (National Demand) already excludes embedded generation (embedded wind
and embedded solar).  It represents grid-supplied demand.  Therefore:

    underlying demand = ND + embedded_wind + embedded_solar
    R = underlying − all_wind − all_solar
      = (ND + embedded_wind + embedded_solar) − (embedded_wind + embedded_solar + W_tx)
      = ND − W_tx

Solar does not appear because it cancels: all embedded solar is already
removed from ND, and there is no transmission-connected solar in GB
at material scale during this period.

### F̄: flexibility adjustment

F̄ is the daily mean of net exports plus pumped-storage consumption:

$$
\bar{F}_d = \frac{1}{N_d} \sum_{t \in d} \bigl(-I_t + P_t\bigr)
$$

where:

- **I_t** = sum of all interconnector flow columns
  (`IFA_FLOW`, `IFA2_FLOW`, `BRITNED_FLOW`, `MOYLE_FLOW`,
  `EAST_WEST_FLOW`, `NEMO_FLOW`, `NSL_FLOW`, `ELECLINK_FLOW`,
  `VIKING_FLOW`, `GREENLINK_FLOW`).
  **NESO sign convention: positive = import to GB**, so net exports =
  −I_t.  Not all interconnectors are present in all years; the sum
  covers whichever columns exist in that year's CSV.

- **P_t** = `PUMP_STORAGE_PUMPING`.
  **NESO sign convention: positive when pumping (consuming electricity)**.

The daily mean smooths intra-day variation in interconnector scheduling
and pump-storage operation, both of which respond to price signals
rather than representing structural demand.

## Units

All source data is in MW.  Conversion to GW (÷ 1000) is applied once
at the final output step in `load_residual_load()`, after the full
computation in MW.

## Sources

### NESO Historic Demand Data

- Portal: <https://neso.energy/data-portal/historic-demand-data>
- Format: one CSV per calendar year
- Licence: Creative Commons Attribution 4.0 (CC BY 4.0)
- Columns used: `SETTLEMENT_DATE`, `SETTLEMENT_PERIOD`, `ND`,
  `PUMP_STORAGE_PUMPING`, `IFA_FLOW`, `IFA2_FLOW`, `BRITNED_FLOW`,
  `MOYLE_FLOW`, `EAST_WEST_FLOW`, `NEMO_FLOW`, `NSL_FLOW`,
  `ELECLINK_FLOW`, `VIKING_FLOW`, `GREENLINK_FLOW`
- Note: ND and TSD are on the BM Reports INDO/ITSDO basis

### Elexon generation by fuel type (FUELHH)

- Endpoint: `https://data.elexon.co.uk/bmrs/api/v1/datasets/FUELHH`
- Query params: `settlementDateFrom`, `settlementDateTo`, `fuelType=WIND`
- No API key required
- Licence: Creative Commons Attribution 4.0 (CC BY 4.0)
- Fields used: `settlementDate`, `settlementPeriod`, `generation`
- This is transmission-connected wind only; embedded wind is already
  accounted for in the ND definition

## Settlement periods and clock changes

GB settlement days run midnight to midnight UK local time.

| Day type | Periods | Example |
|----------|---------|---------|
| Normal | 48 | any day not listed below |
| Spring forward (last Sunday, March) | 46 | 2023-03-26 |
| Fall back (last Sunday, October) | 50 | 2023-10-29 |

Period 1 always starts at 00:00 UK local time.  Conversion to UTC
is handled by `settlement_periods_utc()` in `data/settlement.py`
using `Europe/London` timezone data.

## Out of scope

Regional residual load.  Forecasting.
