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
   Between 1 October 2022 and 30 June 2023, first undo the
   [Energy Price Guarantee adjustment](#energy-price-guarantee).
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
| AGILE-24-10-01 | 95.23 | 100 | 16 Sep 2024 |

AGILE-23-12-06 and AGILE-24-10-01 share the same effective cap (100 p
inc VAT).  For dates before June 2022, only AGILE-18-02-21 is available
(35 p cap), so more slots are capped during high-price periods.

### Source for cap values

Cap values for AGILE-18-02-21 (35 p) and AGILE-22-07-22 (55 p) are
confirmed by observing the API return rates that cluster at exactly the
expected `cap / 1.05` value.  The 78 p cap for AGILE-22-08-31 is
confirmed the same way: 886 region C rates in August–September 2022 sit
at exactly 74.28 (the API truncates 78/1.05 = 74.2857 rather than rounding it).  The
95.23 p cap for AGILE-23-12-06 and AGILE-24-10-01 is confirmed by
observing rates at exactly 95.23 across multiple regions.

## Energy Price Guarantee

From 1 October 2022 to 30 June 2023 (UK local dates) the Energy Price
Guarantee changed how Agile rates were billed.  Once the formula price
went above a floor F, a per-quarter discount D was taken off, but the
billed rate never went below F:

```
billed = formula                 if formula ≤ F
billed = max(formula − D, F)     otherwise
```

Inversion therefore depends on where the billed rate sits:

| Billed rate | Meaning | Treatment |
|---|---|---|
| below F | ordinary formula price | invert as usual |
| at F (±0.001) | formula anywhere in [F, F + D] | **capped** |
| above F, D known | formula − D | add D back, then the usual cap check |
| above F, D unknown | formula − D | **capped** |

Region C values, measured from AGILE-22-08-31:

| Window | F (p/kWh exc VAT) | D (p/kWh exc VAT) |
|---|---|---|
| 1 Oct – 31 Dec 2022 | 34.0926 | 16.9983 |
| 1 Jan – 31 Mar 2023 | 34.0926 | unknown |
| 1 Apr – 30 Jun 2023 | 34.0926 | unknown |

Adding D back makes the 78 p cap show up as 74.28 − 16.9983 = 57.2817.
The usual cap check flags those slots once D is restored.

### Evidence

Outside the window every region C rate has at most two decimal places.
Inside it, only the rates at or above F have four:

| Quarter | At F | Above F | Last two of four decimals above F |
|---|---|---|---|
| Oct–Dec 2022 | 912 | 889 | all `17` |
| Jan–Mar 2023 | 761 | 3 | all `98` |
| Apr–Jun 2023 | 159 | 0 | — |

- **D for Q4 2022.** A 2dp formula price minus 16.9983 always ends in
  `17`, and the highest Q4 rate is 57.2817 = 74.28 − 16.9983, exactly
  the AGILE-22-08-31 cap less D.  57.2817 appears on 303 slots from
  2 October to 17 December 2022.
- **F.** Rates cluster at 34.0926, and at 34.0927 from about
  22 December 2022, presumably a rounding change.  The ±0.001 tolerance
  covers both but doesn't catch a genuine 2dp rate such as 34.09 or 34.10.
- **D for 2023.** Three slots are too few to pin D down, so above-floor
  rates in 2023 are flagged as capped.
- **Window.** The first 4dp rate is at 07:00 UTC on 1 October 2022, and
  the last is on 29 June 2023.  The window runs over whole quarters to
  match the EPG's quarterly discount.

The EPG discount was set per region, so D and F are likely to differ by
region, and only region C has been measured.  Inverting any other region inside
the window raises an error rather than guessing.

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
