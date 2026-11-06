---
covers:
  - data/gas_price.py
  - data/carbon_price.py
  - data/fuel_cost.py
---

# Fuel cost

Daily GB fuel cost k in £ per MWh of electricity: what a typical gas
plant pays in gas and carbon to generate 1 MWh.

## Formula

$$
k_t = \text{HR} \times \bigl(G_t + c_{\text{gas}} \times C_t\bigr)
$$

| Symbol | Description | Unit | Source |
|--------|-------------|------|--------|
| G_t | Gas System Average Price for day t | £/MWh gas | ONS (National Gas Transmission SAP) |
| C_t | Carbon price: ETS, plus Carbon Price Support when `include_carbon_price_support` | £/tCO₂ | gov.uk CCM table (UK ETS), user CSV (EU ETS), HMRC (CPS) |
| HR | `heat_rate` | MWh gas / MWh electricity | config |
| c_gas | `gas_carbon_intensity` | tCO₂ / MWh gas | config |

The emissions factor per MWh of electricity is derived as
c_gas × HR. It is never configured separately.

### Worked example

Gas £25/MWh, ETS £40/t, CPS £18/t, HR 2.0, c_gas 0.184:

    k = 2.0 × (25 + 0.184 × 58) = 2.0 × 35.672 = £71.34/MWh

### Time resolution

G_t is daily and C_t is monthly, held constant within each month.
Each day's k is assigned to every settlement period of that UK
calendar day (46, 48 or 50 periods; see `data/settlement.py`), so the
series joins directly onto the half-hourly wholesale and residual-load
data. Days with no carbon price for their month are dropped.

National Gas's gas day runs 05:00 to 05:00 UK time. SAP for gas day
D is applied to calendar day D. At daily resolution the five-hour
offset is ignored.

### Why HR doesn't affect predictions

HR multiplies k by a constant. The price model fits a coefficient h
on k, so a different HR is absorbed by a proportionally different h,
and the predictions k·h are unchanged. Its exact value doesn't matter.
The gas and carbon series and c_gas do matter, because they set the
relative weight of gas and carbon in k from day to day.

## Parameters

| Parameter | Value | Basis |
|-----------|-------|-------|
| `heat_rate` | 2.0 MWh gas / MWh elec | Equivalent to 50 % thermal efficiency on a gross calorific value basis, typical of the GB CCGT fleet. DESNZ, *Digest of UK Energy Statistics* (DUKES), Chapter 5: plant loads, demand and efficiency. |
| `gas_carbon_intensity` | 0.184 tCO₂ / MWh gas | Natural gas CO₂ emission factor on a gross CV basis (0.184 kgCO₂/kWh). DESNZ, *Greenhouse gas reporting: conversion factors*. Later editions give about 0.183; the difference is well below the uncertainty in HR. |
| `include_carbon_price_support` | true | GB generators pay CPS on top of the ETS price. |

## Units and conversions

| Quantity | Conversion |
|----------|------------|
| p/kWh → £/MWh | × 10 (1000 kWh/MWh ÷ 100 p/£) |
| therm → kWh | 1 therm = 29.3071 kWh, for comparing with sources quoted in p/therm |
| Excel serial → date | days since 1899-12-30 |

The ONS SAP is published in p/kWh, so the loader only needs the
p/kWh → £/MWh step. Gas energy throughout is on a gross calorific
value basis, matching both SAP and the c_gas factor above.

## Sources

### Gas: System Average Price (SAP)

- Publisher: ONS, republishing National Gas Transmission data
- Page: <https://www.ons.gov.uk/economy/economicoutputandproductivity/output/datasets/systemaveragepricesapofgas>
- Format: one XLSX, updated periodically, holding daily SAP from 2018.
  The loader finds the latest file on the landing page, caches it as
  `ons_gas_sap.xlsx`, and reads the "SAP actual day" column.
  It's parsed with the standard library (`zipfile` and
  `xml.etree.ElementTree`), so there's no spreadsheet dependency.
- Unit: p/kWh
- Licence: Open Government Licence v3.0

### Carbon: UK ETS (May 2021 onwards)

- Publisher: DESNZ, on gov.uk
- Page: *Cost Containment Mechanism (CCM) trigger prices and average
  monthly prices: full table*,
  <https://www.gov.uk/government/publications/taking-part-in-the-uk-emissions-trading-scheme-markets/cost-containment-mechanism-ccm-trigger-prices-and-average-monthly-prices-full-table>
- Frequency: **monthly only.** No free daily UKA series was found, so
  monthly averages are used as the issue allows.
- Table layout: each row is an assessment month (e.g. `Aug-21`)
  followed by the average price for each month of its monitoring
  period, which ends just before the assessment month (three months
  in the first table, six in the second). The parser maps each price
  column to its month. Overlapping rows give the same price for a
  month. Cached as `uk_ets_monthly.html`.
- Unit: £/tCO₂
- Licence: Open Government Licence v3.0

### Carbon: EU ETS (before May 2021)

No free, licence-clear download of historical EUA prices in sterling
was found. The loader reads a CSV you supply at
`<cache_dir>/eu_ets_monthly.csv`:

```csv
month,price_gbp_per_tco2
2019-01,20.10
2019-02,...
```

Prices must already be in £/tCO₂ (convert from €/t at the monthly
average EUR/GBP rate). Months in the CSV that the UK ETS table also
covers are overridden by the UK ETS value. The file is not committed
(see `.gitignore`); record its provenance alongside it.

**January to April 2021:** the UK left the EU ETS on 1 January 2021,
but UK ETS auctions only began on 19 May 2021. Generators' 2021
emissions fell under the UK ETS, so the carbon cost in those months
was the expected UKA price, which had no market quote yet. Fill those
months in the CSV with the EU ETS price as a proxy. If you leave them
out, those days are dropped.

### Carbon Price Support (CPS)

HMRC levy on fossil fuels used to generate electricity, set per
financial year (1 April to 31 March). Embedded in `carbon_price.py`:

| Financial year | CPS rate (£/tCO₂) |
|----------------|-------------------|
| 2013–14 | 4.94 |
| 2014–15 | 9.55 |
| 2015–16 onwards | 18.08 |

The rate has been frozen at £18.08 since April 2015. The table runs
to 2027–28. Years after the latest HMRC announcement assume the
freeze continues and should be checked when extending the date range.
A month outside the table raises an error rather than guessing.

- Source: HMRC, *Climate Change Levy: rates and allowances*,
  <https://www.gov.uk/government/publications/rates-and-allowances-climate-change-levy>
- Licence: Open Government Licence v3.0

## Out of scope

Plant-by-plant costs. Coal: its share of GB generation was negligible
over the calibration period (2019–2025), and the last coal plant,
Ratcliffe-on-Soar, closed in September 2024, so k models gas only.
