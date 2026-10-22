"""Homes in a fleet, each with its own ``home_id``.

A home may have no battery. ``identical_homes`` copies one home, including
that choice.
"""

from fleet_sim.models.fleet import Fleet, Home


def identical_homes(home: Home, n_homes: int) -> Fleet:
    """Build ``n_homes`` copies of one home config.

    ``home`` is the config's home: identity, battery, and demand. The copies
    share that battery, demand, region, and transformer. Each ``home_id`` is
    ``{home.home_id}-{index}`` with ``index`` starting at 1, so the copies
    do not share an id.
    """
    if isinstance(n_homes, bool) or not isinstance(n_homes, int):
        raise TypeError(f"n_homes must be an int (got {n_homes!r})")
    if n_homes < 1:
        raise ValueError(f"n_homes must be at least 1 (got {n_homes})")
    copies = [
        home.model_copy(
            update={
                "home_id": f"{home.home_id}-{index}",
                "demand_kw": list(home.demand_kw),
            }
        )
        for index in range(1, n_homes + 1)
    ]
    return Fleet(homes=copies)
