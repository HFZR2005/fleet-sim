# Experiments

A reported number is a mean over replications, with a 95% t-interval. The replication is the independent sample. A day inside a replication is not.

## Why the replication, not the day

One replication draws a fleet once: the households, and the batteries of the homes that own one. It then solves that same fleet on every date in the scenario. Those days share the fleet. They also sit next to each other in the price series, so a cold week shows up in several of them. Averaging the days describes that one fleet. It does not give independent draws, and a t-interval across the days would be too narrow.

The next replication starts from a new master seed, derived from the scenario seed and the replication index. It draws a new fleet and runs the same dates. Replication means are the samples. Their number is `replications` in the scenario, and a t-interval needs at least two.

The half-width is t × s / √R. s is the sample standard deviation of the R replication means, with R − 1 in the divisor. t is the 0.975 quantile of a t distribution on R − 1 degrees of freedom. The interval is that half-width either side of the sample mean.

## Common random numbers

A comparison does not draw two unrelated fleets. Replication i of every condition uses the same derived seed. The households match. Where both conditions assign a battery, the product matches too. What is shared then cancels, mostly, in the difference, and the interval is computed on those paired differences rather than on two separate samples.

Two comparisons are paired that way. With batteries minus without uses the scenario's mode at its penetration and at penetration 0. Diverse minus identical uses the scenario's penetration and changes only the mode.

The technique is common random numbers, one of the standard variance-reduction methods in discrete-event simulation. Law and Kelton, *Simulation Modeling and Analysis*, treat it in the chapter on variance reduction. The point of the pairing is the difference, not the level of either condition on its own.
