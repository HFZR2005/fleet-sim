"""Anchored price response: how fleet schedules shift under a fitted curve.

The real implementation (issue #73) uses the fitted price curve and its
slope to compute how coordinated fleet behaviour changes the wholesale
price.  This module is a placeholder until that issue lands.
"""

from __future__ import annotations

from fleet_sim.prices.curves import FittedCurve
from fleet_sim.stubs import stub


@stub("anchored price response — replace in issue #73")
def price_response_mwh(
    fitted: FittedCurve,
    residual_load_gw: float,
    delta_gw: float,
) -> float:
    """Predicted price change (£/MWh) when load shifts by ``delta_gw``.

    Stub: returns zero.
    """
    _ = fitted, residual_load_gw, delta_gw
    return 0.0
