# Household demand

Homes in a fleet take their half-hourly demand from the UK Power Networks Low Carbon London trial, published by the London Datastore as "SmartMeter Energy Consumption Data in London Households". The trial ran from November 2011 to February 2014 and metered 5,567 households. The pool keeps both tariff groups. About 1,100 households were on a dynamic time-of-use tariff during 2013, and the rest were on a flat tariff. The file's `stdorToU` column records which, and it is not used to drop households.

The download is cached under `.cache/lcl`, which is outside the repository. `ingest_low_carbon_london` reads the official CSV, a directory of the partitioned CSVs, or a zip of those files, and writes `.cache/lcl/household_days.csv`. The London Datastore zip is compressed with Deflate64. Python's zip reader cannot inflate that, so that archive is streamed through the `unzip` command. Tests never download the file. They read `tests/fixtures/lcl_household_days.csv`, a few real rows taken out of the official CSV.

## A complete day

`DateTime` is the end of the half hour, in UK civil time, with no timezone. The slot starts 30 minutes earlier, and the civil day is the date of that start. A stamp of `00:00:00` therefore belongs to the previous day.

A day is kept when it has 48 distinct half hours and every reading is a number of at least 0 kWh. A blank, `Null`, or negative reading drops the day. A repeated half hour drops the day. A clock-change day that contains 46 or 50 half hours drops the day. The fixture includes 12 October 2012, which has 47 half hours because the meter starts that day, and 19 December 2012, which contains a `Null`.

## From a simulated date to a trial date

The trial is not replayed as a year. A simulated date is matched to the trial by Elexon season and by weekday or weekend, using the same season boundaries as the Profile Class 1 demand (`elexon_season` in `src/fleet_sim/data/demand.py`). Saturday and Sunday are the weekend. A bank holiday that falls on a weekday stays a weekday.

Each home is given one household for the whole run. The ids are sorted, and `n_homes` of them are drawn without replacement from the `demand` stream. The same master seed assigns the same households, and drawing another named stream does not move this one. A fleet larger than the pool is rejected. Two homes never share a household. Using a household twice is a later decision.

On a simulated date the home uses that household's trial day in the same season and the same weekday-or-weekend bin. When several days sit in the bin, the one whose position in the year is closest to the simulated date is used. The distance is around a non-leap year: 29 February is treated as 28 February, and the year used for the day number is 2001. A tie prefers the same weekday-or-weekend type, and a remaining tie prefers the earlier trial date.

If the household has no day in that bin, the same rule runs over every complete day that household does have. `HouseholdLoad.fallback` then records the household, the simulated date, the trial date that was used, and the season and day type that were missing. That record is what a run stores in its metadata. The returned `DemandSeries` is labelled with the simulated date. The half hours are the trial day's.

## What the trial does not contain

The meters predate widespread heat pumps and electric vehicles, so these days do not carry those loads. A home with a heat pump or a car charger would look different from any day in this pool.
