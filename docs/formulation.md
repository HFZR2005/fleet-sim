# One-home problem

This note specifies the optimisation problem for a single home battery over one day. The battery chooses when to charge and discharge so as to minimise the cost of electricity imported from the grid. Demand and the import price are known parameters. Later optimiser code implements the equations in this file.

Export payments, on-site solar, degradation, and forecasts are out of this problem. They are named under [Later extensions](#later-extensions).

## Notation

The import tariff is $`p_t`$. Usable storage at a full battery is $`E`$, in kWh. $`\lambda`$ is reserved for Lagrange multipliers in later milestones, when a coordinator prices a shared constraint. It is not a price in this note.

## Time grid

A day is $`T = 48`$ slots, indexed $`t = 0, \ldots, T - 1`$. Each slot lasts

$$
\Delta = 0.5 \text{ hours}.
\tag{DT}
$$

Energy in kWh over a slot is power in kW times $`\Delta`$. In code that factor is `0.5`. The worked example below uses the same slot length with a shorter horizon, $`T = 2`$, so the same equations can be checked by hand.

British Summer Time changes the length of two civil days. The spring change has 46 half-hour slots and the autumn change has 50. This problem is a 48-slot day on a day that lasts 24 hours. The Agile import price loader rejects the 46- and 50-slot dates with an error and does not return a shorter or longer series.

## Parameters

| Code name | Symbol | Domain | Unit |
| --- | --- | --- | --- |
| `capacity_kwh` | $`E`$ | $`> 0`$ | kWh of stored energy at state of charge 1 |
| `max_charge_kw` | $`\bar{c}`$ | $`\geq 0`$ | kW |
| `max_discharge_kw` | $`\bar{d}`$ | $`\geq 0`$ | kW |
| `eta_charge` | $`\eta^{c}`$ | $`(0, 1]`$ | fraction stored per unit of AC energy drawn to charge |
| `eta_discharge` | $`\eta^{d}`$ | $`(0, 1]`$ | fraction delivered as AC energy per unit taken from the store |
| `soc_initial` | $`s_0`$ | $`[0, 1]`$ | state of charge at the start of slot 0 |
| `demand_kw[t]` | $`L_t`$ | $`\geq 0`$ | kW, average house load in slot $`t`$ |
| `price_p_per_kwh[t]` | $`p_t`$ | real | pence per kWh imported in slot $`t`$ |
| `price_adjustment_p_per_kwh[t]` | $`a_t`$ | real, default 0 | pence per kWh added to the tariff in the objective |

State of charge is a fraction in $`[0, 1]`$. Both efficiencies are fractions in $`(0, 1]`$. Zero is rejected for either efficiency: the state-of-charge update divides by discharge efficiency. A number such as 90 is rejected as well: 90% is written 0.9.

`demand_kw` is average power in kW over the slot, the same unit as charge and discharge. The house's energy in that slot is `demand_kw * 0.5` kWh. One kilowatt for the half hour is half a kilowatt-hour. A day carries 48 `demand_kw` values and 48 `price_p_per_kwh` values. `price_adjustment_p_per_kwh` has one value per slot when it is passed in. Omitted, every $`a_t`$ is zero.

A price may be negative: the import tariff then pays the household for each imported kWh.

## Decision variables

For each slot $`t = 0, \ldots, T - 1`$:

| Code name | Symbol | Unit | Meaning |
| --- | --- | --- | --- |
| `charge_kw[t]` | $`c_t`$ | kW | AC power drawn from the house bus into the battery |
| `discharge_kw[t]` | $`d_t`$ | kW | AC power delivered from the battery onto the house bus |
| `grid_import_kw[t]` | $`g_t`$ | kW | AC power imported from the grid |
| `soc[t]` | $`s_{t+1}`$ | fraction | state of charge at the end of slot $`t`$ |
| `charge_mode[t]` | $`y_t`$ | $`\{0, 1\}`$ | which power-flow direction the slot allows |

`charge_kw`, `discharge_kw`, `grid_import_kw`, and `demand_kw` are all average AC power on the house bus. The mode variable is the device that stops a slot charging and discharging at once; it is defined in [Simultaneous charge and discharge](#simultaneous-charge-and-discharge). The other four are the physical schedule.

`soc_initial` is $`s_0`$, the state of charge before slot 0. It is a parameter. `soc[t]` stores $`s_{t+1}`$, the state of charge after slot $`t`$ has elapsed. The end of the day is `soc[T - 1]`, which is $`s_T`$.

## Constraints

### State of charge

$$
s_{t+1}
  = s_t
  + \frac{\Delta}{E}
    \left(
      \eta^{c}\, c_t
      - \frac{d_t}{\eta^{d}}
    \right),
  \qquad t = 0, \ldots, T - 1.
\tag{SOC}
$$

Charging power $`c_t`$ draws $`c_t \Delta`$ kWh from the bus and stores the fraction $`\eta^{c}`$. Discharge power $`d_t`$ delivers $`d_t \Delta`$ kWh to the bus and removes $`d_t \Delta / \eta^{d}`$ kWh from the store. In code, with `soc_prev = soc_initial` when `t == 0` and `soc_prev = soc[t - 1]` otherwise:

```text
soc[t] = soc_prev
    + (
        eta_charge * charge_kw[t] * 0.5
        - discharge_kw[t] * 0.5 / eta_discharge
      ) / capacity_kwh
```

### Bounds

$$
0 \leq s_t \leq 1,
  \qquad t = 1, \ldots, T.
\tag{SOC-BOUNDS}
$$

$$
0 \leq c_t \leq \bar{c},
  \qquad
0 \leq d_t \leq \bar{d},
  \qquad
g_t \geq 0.
\tag{POWER-BOUNDS}
$$

$`g_t \geq 0`$ is the no-export rule: the house does not send power to the grid. The upper bounds on $`c_t`$ and $`d_t`$ are the inverter limits. [Simultaneous charge and discharge](#simultaneous-charge-and-discharge) tightens those upper bounds with $`y_t`$.

### Energy balance

The bus balances in every slot. House load and battery charging are supplied by grid import and battery discharge:

$$
g_t + d_t = L_t + c_t,
  \qquad t = 0, \ldots, T - 1.
\tag{BALANCE}
$$

Given $`c_t`$, $`d_t`$, and $`L_t`$, this equality fixes $`g_t`$. The import stays a decision variable so the no-export bound and the objective are written on it directly.

### End of day

$$
s_T = s_0.
\tag{TERMINAL}
$$

In code, `soc[T - 1] == soc_initial`.

The objective prices grid imports during the day and does not price energy that is already in the battery at $`s_0`$. With no condition on $`s_T`$, that stored energy is free. Whenever import prices are positive, discharging it cuts the bill and nothing charges the household for the energy taken out of the store, so the minimiser empties the battery. Equality with the starting state of charge closes that. Every kWh taken out has to be put back before the day ends, and a lower bill then comes from moving energy between prices.

The same equality covers a day that contains negative prices. A free ending state of charge would let the schedule finish full of energy the tariff paid the household to absorb, and the next day would inherit that store. Finishing where the day started means every kWh kept was paid for inside the day.

## Objective

Minimise the adjusted import cost in pence:

$$
\sum_{t=0}^{T-1} (p_t + a_t) \, g_t \, \Delta.
\tag{COST}
$$

$`g_t \Delta`$ is imported energy in kWh. $`p_t`$ is the import tariff and $`a_t`$ is the price adjustment, both in pence per kWh. $`a_t`$ is how a later coordinator, and through it a network limit, will reach this home: the home keeps solving the same problem, and the only new input is that per-slot price. It is zero unless that coordinator sets it.

The solver minimises (COST). The schedule's `cost_pence` is the household's tariff bill and leaves the adjustment out:

$$
\sum_{t=0}^{T-1} p_t \, g_t \, \Delta.
$$

In code that bill is `price_p_per_kwh[t] * grid_import_kw[t] * 0.5`. When every $`a_t`$ is zero, the bill and (COST) are the same number. The worked example is that case.

## Simultaneous charge and discharge

(SOC), (BALANCE), and (POWER-BOUNDS) are linear, and they allow $`c_t > 0`$ and $`d_t > 0`$ in the same slot. That pair is not a useful inverter schedule. It is an artefact of treating the two powers as independent.

Hold the stored energy fixed across the slot by setting

$$
d_t = \eta^{c} \eta^{d}\, c_t.
$$

(BALANCE) then gives an import strictly above the load whenever the round trip loses energy:

$$
g_t
  = L_t + c_t \bigl(1 - \eta^{c} \eta^{d}\bigr).
$$

The extra import is the energy turned into heat. If $`p_t > 0`$, that heat is bought at a positive price, so it cannot help the bill. If $`p_t < 0`$, the tariff pays for it. Cycling both powers, and holding the state of charge still, can then be optimal. It remains available when the battery is full, where a pure charge would break the state-of-charge cap, and when the terminal condition forbids a net gain over the day. The linear program takes that payment. A home inverter carries power in one direction at a time, so the payment is not a real option.

The solve drops (MODE) first. That linear program is priced at the effective price $`p_t + a_t`$, not at the tariff alone. If any slot comes back with both powers positive, past a small tolerance, the home is solved again with (MODE) and that is the schedule that is kept. Both powers are profitable only when $`p_t + a_t`$ is negative, so a positive tariff does not by itself mean the linear program is safe: a negative adjustment can still pay for the loss, and a positive adjustment can stop a negative tariff from paying for it. The schedule records which of the two solves produced it.

The formulation shuts the artefact off with one binary per slot:

$$
c_t \leq \bar{c}\, y_t,
  \qquad
d_t \leq \bar{d}\, (1 - y_t),
  \qquad
y_t \in \{0, 1\}.
\tag{MODE}
$$

$`y_t = 1`$ allows charging and forces `discharge_kw[t] = 0`. $`y_t = 0`$ allows discharging and forces `charge_kw[t] = 0`. Both powers may be zero in either mode, so an idle slot does not have a unique `charge_mode`. With (MODE) the program is a mixed-integer linear program. Dropping $`y_t`$ brings back the linear program that can earn money by cycling on a negative price.

Illustration, separate from the test case. One slot, $`T = 1`$, $`L_0 = 0`$, $`p_0 = -8`$, $`E = 2`$, $`\eta^{c} = \eta^{d} = 0.5`$, $`\bar{c} = \bar{d} = 4`$, and (TERMINAL) in force. (SOC) with $`s_1 = s_0`$ gives $`c_0 = 4 d_0`$. Import is $`g_0 = 3 d_0`$. The charge limit binds at $`d_0 = 1`$, $`c_0 = 4`$, hence $`g_0 = 3`$ kW and $`1.5`$ kWh imported. Because the price is negative, that point is the linear program's optimum. (COST) is $`-8 \times 1.5 = -12`$ pence, twelve pence earned for dissipating a loss. (MODE) forbids that point. The only feasible schedule is $`c_0 = d_0 = g_0 = 0`$, with bill 0.

## Worked example

This is the instance to reuse as a test. Horizon $`T = 2`$, slot length (DT). Every price adjustment is zero, so (COST) is the tariff bill. The mode constraints are satisfied, and the schedule below is also the unique minimiser of (COST) subject only to (SOC), (SOC-BOUNDS), (POWER-BOUNDS), (BALANCE), and (TERMINAL).

| Parameter | Value |
| --- | --- |
| `capacity_kwh` | 2 |
| `max_charge_kw` | 8 |
| `max_discharge_kw` | 2 |
| `eta_charge` | 0.5 |
| `eta_discharge` | 0.5 |
| `soc_initial` | 0.25 |
| `demand_kw` | `[1, 1]` |
| `price_p_per_kwh` | `[2, 10]` |

Substitute $`\Delta`$, $`E`$, and the efficiencies into (SOC):

$$
s_{t+1} = s_t + 0.125\, c_t - 0.5\, d_t.
$$

(TERMINAL) says $`s_2 = s_0`$, so the two steps sum to zero:

$$
c_0 + c_1 = 4 (d_0 + d_1).
\tag{EX-CYCLE}
$$

(BALANCE) with $`L_t = 1`$ gives $`g_0 = 1 + c_0 - d_0`$ and $`g_1 = 1 + c_1 - d_1`$. (COST) in pence is

$$
2 \cdot g_0 \cdot 0.5 + 10 \cdot g_1 \cdot 0.5
  = g_0 + 5 g_1
  = 6 + c_0 - d_0 + 5 c_1 - 5 d_1.
$$

Replace $`c_0`$ using (EX-CYCLE):

$$
\text{bill}
  = 6 + 3 d_0 - d_1 + 4 c_1,
  \qquad
\text{bill} - 5
  = 1 + 3 d_0 - d_1 + 4 c_1.
$$

$`g_1 \geq 0`$ says $`d_1 \leq 1 + c_1`$, so $`-d_1 \geq -1 - c_1`$. Therefore

$$
\text{bill} - 5
  \geq 1 + 3 d_0 - 1 - c_1 + 4 c_1
  = 3 d_0 + 3 c_1
  \geq 0,
$$

because $`d_0 \geq 0`$ and $`c_1 \geq 0`$. The bill is at least 5 pence. Equality needs $`d_0 = 0`$, $`c_1 = 0`$, and $`d_1 = 1 + c_1`$, hence $`d_1 = 1`$. (EX-CYCLE) then gives $`c_0 = 4`$.

That point is inside the remaining bounds: $`c_0 = 4 \leq 8`$, $`d_1 = 1 \leq 2`$, $`g_0 = 5 \geq 0`$, $`g_1 = 0`$, and the states of charge from (SOC) are $`s_1 = 0.75`$ and $`s_2 = 0.25`$. Both lie in $`[0, 1]`$. No other feasible point reaches 5 pence, so the schedule is unique:

| $`t`$ | `charge_kw` | `discharge_kw` | `grid_import_kw` | `soc` at end of slot | `charge_mode` |
| --- | --- | --- | --- | --- | --- |
| 0 | 4 | 0 | 5 | 0.75 | 1 |
| 1 | 0 | 1 | 0 | 0.25 | 0 |

The bill is 5 pence. Slot 0 imports $`2.5`$ kWh at 2 p/kWh. Slot 1 imports nothing: the battery covers the 1 kW load, and $`s_2`$ is back at $`0.25`$.

Without the battery, $`g_t = L_t`$ and the bill is $`0.5 \times 2 + 0.5 \times 10 = 6`$ pence. The battery saves 1 pence by buying the evening load in the cheap slot, including the energy the round trip loses.

## Realistic worked example

Same horizon and slot length, with efficiencies and power limits in the range of a home battery. The inverter limits do not bind: the house load and the round-trip loss do. Every adjustment is zero.

| Parameter | Value |
| --- | --- |
| `capacity_kwh` | 10 |
| `max_charge_kw` | 5 |
| `max_discharge_kw` | 5 |
| `eta_charge` | 0.95 |
| `eta_discharge` | 0.95 |
| `soc_initial` | 0.5 |
| `demand_kw` | `[1, 1]` |
| `price_p_per_kwh` | `[10, 20]` |

$`\Delta / E = 0.05`$. Substituting the efficiencies,

$$
s_{t+1} = s_t + 0.0475\, c_t - \frac{d_t}{19}.
$$

(TERMINAL) forces $`d_0 + d_1 = 0.9025\,(c_0 + c_1)`$, and $`0.9025 = 0.95^2`$ is the fraction of charged energy that comes back as discharge. (BALANCE) with $`L_t = 1`$ is $`g_t = 1 + c_t - d_t`$. (COST) in pence is

$$
5 g_0 + 10 g_1 = 15 + 5 c_0 - 5 d_0 + 10 c_1 - 10 d_1.
$$

Replace $`d_0`$ using (TERMINAL):

$$
\text{bill} = 15 + \frac{39}{80} c_0 + \frac{439}{80} c_1 - 5 d_1.
$$

The coefficient of $`d_1`$ is negative, so a minimum takes $`d_1`$ as large as the bounds allow. $`g_1 \geq 0`$ says $`d_1 \leq 1 + c_1`$, $`d_0 \geq 0`$ says $`d_1 \leq 0.9025\,(c_0 + c_1)`$, and the inverter says $`d_1 \leq 5`$. On the face $`d_1 = 1 + c_1`$, which needs $`c_0 \geq 400/361 + (39/361)\, c_1`$,

$$
\text{bill} = 10 + \frac{39}{80}(c_0 + c_1).
$$

That expression falls as $`c_0 + c_1`$ falls, and the smallest sum on the face is $`c_1 = 0`$, $`c_0 = 400/361`$. Then $`d_0 = 0`$, $`d_1 = 1`$, $`g_0 = 761/361`$, $`g_1 = 0`$. The bill is $`3805/361`$ pence, about 10.540. Charge is about 1.108 kW and discharge is 1 kW, both under the 5 kW limits. The states of charge are $`s_1 = 1/2 + 19/361`$ and $`s_2 = 1/2`$.

On the other face, $`d_0 = 0`$, the bill is $`15 - 4.025\, c_0 + 0.975\, c_1`$, which is higher for every smaller $`c_0`$. Setting $`d_1`$ to the inverter limit forces a large $`c_1`$ and a higher bill. The schedule is unique:

| $`t`$ | `charge_kw` | `discharge_kw` | `grid_import_kw` | `soc` at end of slot | `charge_mode` |
| --- | --- | --- | --- | --- | --- |
| 0 | $`400/361`$ | 0 | $`761/361`$ | $`1/2 + 19/361`$ | 1 |
| 1 | 0 | 1 | 0 | $`1/2`$ | 0 |

Without the battery the bill is $`0.5 \times 10 + 0.5 \times 20 = 15`$ pence. The battery saves about 4.460 pence. The round trip returns 90.25% of the energy it took from the cheap slot, and $`10 < 0.9025 \times 20`$, so moving the second slot's load into the first slot still pays.

## Fleet measures

These describe a fleet of homes that have each already solved the one-home problem. They are not constraints on that problem.

The root-node flow $`F_t`$ is the sum of the homes' grid imports in slot $`t`$. Peak demand is the greatest $`F_t`$, and the peak slot is the earliest $`t`$ that attains it. The without-battery peak is the same measure on the sum of the homes' demand, the import there would have been with no batteries.

The peak-to-average ratio is the peak divided by the mean of $`F_t`$ over the day. When that mean is zero the ratio is zero.

The coincidence factor is the fleet peak divided by the sum of the homes' own peaks. Each home's peak is the greatest import in its own schedule. When every one of those peaks is zero, the factor is zero. Identical homes that charge in the same slot have a factor of 1: the fleet peak is just the peaks stacked.

Savings are in pence. A home's saving is its no-battery bill minus its tariff bill. The fleet's total saving is the sum of those, and the saving per home is the total divided by the number of homes. The tariff bill leaves any price adjustment out, as in (COST).

## Later extensions

These are not part of the model above.

- **Export payments.** A separate export power and an export price, so the house can be paid for power sent to the grid.
- **Solar.** Photovoltaic generation as a further inflow on the bus, reducing what the load and the charger draw from the grid.
- **Degradation.** A cost on throughput or on cycles, so the bill is no longer import cost alone.
- **Forecasts.** Demand and import prices are data in this problem. A later model can replace them with predictions and say how the schedule is revised when those predictions change.
