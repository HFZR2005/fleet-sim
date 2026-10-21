"""Frames written to JSON and read back as the same models."""

from datetime import UTC, date, datetime
from pathlib import Path

from fleet_sim.fleet import FleetDay, SolvedHome
from fleet_sim.fleet.frames import frames_for_day, read_frames, write_frames
from fleet_sim.fleet.network import NodeFeedback
from fleet_sim.models import PriceSeries, Schedule


def _schedule() -> Schedule:
    return Schedule(
        charge_kw=[4.0, 0.0],
        discharge_kw=[0.0, 1.0],
        grid_import_kw=[5.0, 0.0],
        soc=[0.75, 0.25],
        charge_mode=[1, 0],
        cost_pence=5.0,
    )


def test_frames_round_trip(tmp_path: Path) -> None:
    start = datetime(2024, 6, 14, 23, 0, tzinfo=UTC)
    later = datetime(2024, 6, 15, 0, 0, tzinfo=UTC)
    prices = PriceSeries.model_construct(
        region="C",
        day=date(2024, 6, 15),
        timestamps_utc=[start, later],
        price_p_per_kwh=[2.0, 10.0],
    )
    solved = FleetDay(
        homes=[
            SolvedHome(
                home_id="home-1",
                transformer_id="tx-1",
                demand_kw=[1.0, 1.0],
                schedule=_schedule(),
            )
        ],
        nodes=[
            NodeFeedback(
                node_id="root",
                flow_kw=[5.0, 0.0],
                limit_kw=None,
                overload_kw=[0.0, 0.0],
            )
        ],
    )
    frames = frames_for_day(prices, solved)
    path = tmp_path / "frames.json"
    write_frames(path, frames)

    loaded = read_frames(path)

    assert loaded.schema_version == 1
    assert loaded.frames == frames
    assert loaded.frames[0].homes[0].mode == "charging"
    assert loaded.frames[1].homes[0].mode == "discharging"
    assert loaded.frames[0].slot_start == start
    assert loaded.frames[0].nodes[0].flow_kw == 5.0
    text = path.read_text(encoding="utf-8")
    assert '"schema_version": 1' in text
