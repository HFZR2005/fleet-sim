---
covers:
  - data/agile_formula.py
  - data/agile_history.py
  - data/wholesale.py
---

# Agile tariff inversion

This document describes how half-hourly wholesale electricity prices are
recovered from the Octopus Agile retail tariff.

## Formula

The Agile tariff sets each half-hour retail rate from the national
day-ahead wholesale price:

```
value_exc_vat = min(wholesale_p × multiplier + peak_adder, cap)
value_inc_vat = value_exc_vat × 1.05
```

where:

| Parameter    | Scope            | Description |
|---|---|---|
| `wholesale_p` | National, half-hourly | Day-ahead wholesale price (p/kWh) |
| `multiplier`  | Per region       | Accounts for regional transmission and distribution losses |
| `peak_adder`  | Per region, peak only | Added during the 4–7 pm UK-local window; zero outside it |
| `cap`         | Per product version | Maximum exc-VAT rate; see [Product versions](#product-versions) |

VAT is 5 % on domestic electricity, applied uniformly across all product
versions and dates checked.

### Peak window

The peak adder applies when the settlement period's start time falls
between 16:00 and 18:30 UK local time (i.e. 4–7 pm inclusive of the
half-hour starting at 18:30).  In UTC this is:

- **GMT (winter):** 16:00–19:00 UTC
- **BST (summer):** 15:00–18:00 UTC

## Inversion

To recover the wholesale price from a retail rate:

1. Read `value_exc_vat` from the Octopus API.
2. If `value_exc_vat ≥ cap − 0.1`: the slot is **capped**.  The
   wholesale price cannot be recovered; flag the slot and skip it.
3. Otherwise:
   - Off-peak: `wholesale_p = value_exc_vat / multiplier`
   - Peak: `wholesale_p = (value_exc_vat − peak_adder) / multiplier`
4. Convert: `wholesale_gbp_per_mwh = wholesale_p × 10`

The 0.1 p/kWh tolerance on cap detection accounts for the API rounding
`value_exc_vat` to two decimal places (e.g. the true cap 35/1.05 =
33.333… is stored as 33.33).

## Product versions

Each Agile product version differs primarily in its price cap.  The
Octopus API still serves historical rates for all versions, and multiple
versions overlap in time (offered to different customer cohorts).  For
uncapped slots, all versions return identical `value_exc_vat` values —
they share the same formula parameters, differing only in cap.

The loader selects the version with the highest cap for each date to
minimise the number of capped (lost) slots.

| Product | Cap exc VAT (p/kWh) | Cap inc VAT (p/kWh) | Data from |
|---|---|---|---|
| AGILE-18-02-21 | 33.33 | 35 | ~Feb 2018 |
| AGILE-22-07-22 | 52.38 | 55 | ~Jun 2022 |
| AGILE-22-08-31 | 74.29 | 78 | ~Aug 2022 |
| AGILE-23-12-06 | 95.23 | 100 | ~Dec 2023 |
| AGILE-24-10-01 | 95.23 | 100 | ~Sep 2024 |

AGILE-23-12-06 and AGILE-24-10-01 share the same effective cap (100 p
inc VAT).  For dates before June 2022, only AGILE-18-02-21 is available
(35 p cap), so more slots are capped during high-price periods.

### Source for cap values

Cap values for AGILE-18-02-21 (35 p) and AGILE-22-07-22 (55 p) are
confirmed by observing the API return rates that cluster at exactly the
expected `cap / 1.05` value.  The 78 p cap for AGILE-22-08-31 is from
third-party reporting and has not been observed to bind in the data
checked (prices in the available date range stayed below it).  The
95.23 p cap for AGILE-23-12-06 and AGILE-24-10-01 is confirmed by
observing rates at exactly 95.23 across multiple regions.

## Regional parameters

| Region | Multiplier | Peak adder (p/kWh) |
|---|---|---|
| A (Eastern England) | 2.10 | 13 |
| B (East Midlands) | 2.00 | 14 |
| C (London) | 2.00 | 12 |
| D (Merseyside, North Wales) | 2.20 | 13 |
| E (West Midlands) | 2.10 | 12 |
| F (North East England) | 2.10 | 12 |
| G (North West England) | 2.10 | 12 |
| H (Southern England) | 2.10 | 12 |
| J (South East England) | 2.20 | 12 |
| K (South Wales) | 2.20 | 12 |
| L (South West England) | 2.30 | 11 |
| M (Yorkshire) | 2.00 | 13 |
| N (South Scotland) | 2.10 | 13 |
| P (North Scotland) | 2.40 | 12 |

### Source for regional parameters

**These values are from a third-party source (agilerates.co.uk) and are
not confirmed by Octopus Energy's own documentation.**  They have been
cross-verified against the Octopus API: inverting the same half-hour
slot from two different regions using these parameters yields the same
wholesale price (within API rounding precision of ±0.01 p/kWh).

The multipliers likely represent regional Line Loss Factors, which
change annually.  It is possible that the values listed here are current
only for the AGILE-24-10-01 product.  However, empirical testing shows
identical `value_exc_vat` for uncapped slots across product versions for
the same region, which implies the multipliers have not changed between
versions.

## Cross-region consistency

Inverting the same settlement period from two different regions should
give the same wholesale price (since wholesale is a national market).
Empirical checks confirm this:

- Regions C and A, off-peak: wholesale prices agree to within 0.01 p/kWh
- Regions C and A, peak: wholesale prices agree to within 0.01 p/kWh

Any disagreement beyond rounding indicates either a formula error or a
change in regional parameters.

## Elexon cross-check

*Pending: a notebook analysis comparing the inverted wholesale prices
against Elexon's Market Index Data Reference Price (MIDP) will be added
here.  The two series measure slightly different things (Agile wholesale
is the day-ahead auction price; MIDP is a volume-weighted within-day
reference), so an exact match is not expected.  The check is for gross
errors — e.g. the inverted prices should correlate strongly and differ
by no more than a few £/MWh on average.*

## Implementation

- `fleet_sim.data.agile_formula` — formula models, `invert_agile()`,
  `apply_agile()`, version and region parameter tables
- `fleet_sim.data.agile_history` — bulk historical rate fetcher with
  per-month caching
- `fleet_sim.data.wholesale` — `load_wholesale_prices()` entry point
  that fetches, inverts, and drops capped slots
