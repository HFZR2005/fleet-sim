"""Build a day's frames and write them to one JSON file."""

import json
from pathlib import Path

from fleet_sim.fleet.solve import FleetDay
from fleet_sim.models.frames import Frame, FrameLog, HomeFrame, HomeMode, NodeFrame
from fleet_sim.models.prices import PriceSeries


def frames_for_day(prices: PriceSeries, day: FleetDay) -> list[Frame]:
    """One frame per slot of ``prices``, from a solved fleet day."""
    n_slots = len(prices.price_p_per_kwh)
    if len(prices.timestamps_utc) != n_slots:
        raise ValueError(
            "timestamps and prices must have the same length "
            f"(got {len(prices.timestamps_utc)} and {n_slots})"
        )
    frames: list[Frame] = []
    for slot in range(n_slots):
        homes: list[HomeFrame] = []
        for home in day.homes:
            schedule = home.schedule
            if len(schedule.soc) != n_slots:
                raise ValueError(
                    f"home {home.home_id} must cover {n_slots} slots "
                    f"(got {len(schedule.soc)})"
                )
            homes.append(
                HomeFrame(
                    home_id=home.home_id,
                    transformer_id=home.transformer_id,
                    soc=schedule.soc[slot],
                    mode=_mode(schedule.charge_kw[slot], schedule.discharge_kw[slot]),
                    import_kw=schedule.grid_import_kw[slot],
                    demand_kw=home.demand_kw[slot],
                )
            )
        nodes = [
            NodeFrame(
                node_id=node.node_id,
                flow_kw=node.flow_kw[slot],
                limit_kw=node.limit_kw,
                overload_kw=node.overload_kw[slot],
            )
            for node in day.nodes
        ]
        frames.append(
            Frame(
                slot_start=prices.timestamps_utc[slot],
                price_p_per_kwh=prices.price_p_per_kwh[slot],
                homes=homes,
                nodes=nodes,
            )
        )
    return frames


def write_frames(path: Path, frames: list[Frame]) -> None:
    """Write ``frames`` as one JSON file with schema version 1."""
    log = FrameLog(schema_version=1, frames=frames)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(log.model_dump(mode="json"), indent=2) + "\n",
        encoding="utf-8",
    )


def read_frames(path: Path) -> FrameLog:
    """Read a frame file back into the same models."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    return FrameLog.model_validate(raw)


def _mode(charge_kw: float, discharge_kw: float) -> HomeMode:
    if charge_kw > 0.0 and discharge_kw > 0.0:
        raise ValueError("a slot cannot charge and discharge")
    if charge_kw > 0.0:
        return "charging"
    if discharge_kw > 0.0:
        return "discharging"
    return "idle"
