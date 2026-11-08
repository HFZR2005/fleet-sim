---
covers:
  - prices/curves.py
---

# Constant-σ normal noise

The price curves are fitted by censored maximum likelihood with noise $`\varepsilon_i \sim N(0, \sigma^2)`$ on the target $`y_i`$, with one constant $`\sigma`$ fitted jointly with the curve. With no censored slots this is least squares.

The alternative was a $`\sigma`$ that grows with residual load $`R`$. The evidence is in `notebooks/price-curves/02-noise-model.ipynb`: residuals of exact slots, training years 2021–2024, from an isotonic fit, with a cubic-with-offset fit as a check.

## Evidence

The spread is U-shaped in $`R`$. It does not rise steadily. Robust scale of the fuel-adjusted residual ($`1.4826 \times`$ the median absolute deviation, in units of $`\pi / k`$):

| Year | Below 8 GW | 10–15 GW | 25–30 GW |
| --- | --- | --- | --- |
| 2021 | 0.27 | 0.10 | 0.17 |
| 2022 | 0.29 | 0.17 | 0.26 |
| 2023 | 0.33 | 0.13 | 0.16 |
| 2024 | 0.29 | 0.13 | 0.15 |

The spread is largest at low $`R`$, in the renewables-heavy regime with negative prices. Any $`\sigma`$ that increases with $`R`$ would shrink it there. The raw target shows the same shape, with a steeper rise at high $`R`$ (1.5–1.9× from 10–15 to 25–30 GW). Part of that rise comes from $`k`$ being higher when $`R`$ is high, but not all of it.

**2022 is the exception.** In the gas-crisis year the spread grows with $`R`$ in every target, and nearly doubles from 15 to 30 GW in the fuel-adjusted one. 2021 rises 1.6× too. Censoring removes the largest residuals at high $`R`$, so in these two years the true rise is, if anything, larger than measured.

The tails are heavier than normal. In 2022–2024, 2.6–3.6% of fuel-adjusted residuals lie beyond three scales (normal: 0.27%), and the excess kurtosis is 4.7–7.4. Standardising within each $`R`$ bin barely changes this, so the heavy tails do not come from the spread changing with $`R`$.

## What it gives up

- **σ too small where the censored slots are.** In 2021 and 2022, $`\sigma`$ is understated at high $`R`$, which is where most censored slots lie. A censored slot contributes $`\log P(y \ge y^{\text{lower}})`$. With $`\sigma`$ too small and normal tails too thin, that term is too sure the price sat just above its bound, so the fit will tend to place those slots too low. 2021, about a third censored, leans on this most.
- **σ too large in the middle.** It is overstated at 10–20 GW and understated below 8 GW.
- **Noise proportional to k in the fuel-adjusted target.** The model is $`\pi = k\,h(R) + \varepsilon`$. A constant $`\sigma`$ on $`y = \pi / k`$ means $`\varepsilon`$ has spread proportional to $`k`$. The raw target puts a constant $`\sigma`$ on $`\pi`$ itself.

A U-shaped or heavier-tailed noise model would address these points. Both are out of scope for the first censored fit (#86).
