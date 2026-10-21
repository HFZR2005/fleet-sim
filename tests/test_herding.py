"""Herding figures drawn from frames, with no solve."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from fleet_sim.models.frames import Frame, HomeFrame, NodeFrame
from fleet_sim.viz.herding import plot_daily_peaks, plot_herding
from fleet_sim.viz.save import save_figure

_START = datetime(2024, 6, 14, 23, 0, tzinfo=UTC)


def _frame(slot: int, flow_kw: float, demand_kw: float, price: float) -> Frame:
    return Frame(
        slot_start=_START + timedelta(minutes=30 * slot),
        price_p_per_kwh=price,
        homes=[
            HomeFrame(
                home_id="home-1",
                transformer_id=None,
                soc=0.5,
                mode="idle",
                import_kw=flow_kw,
                demand_kw=demand_kw,
            )
        ],
        nodes=[
            NodeFrame(
                node_id="root",
                flow_kw=flow_kw,
                limit_kw=None,
                overload_kw=0.0,
            )
        ],
    )


def test_herding_and_peak_figures_save_from_frames(tmp_path: Path) -> None:
    frames = [
        _frame(0, flow_kw=5.0, demand_kw=1.0, price=2.0),
        _frame(1, flow_kw=0.0, demand_kw=1.0, price=10.0),
    ]
    herding = save_figure(plot_herding(frames), tmp_path / "herding")
    peaks = save_figure(
        plot_daily_peaks(
            [
                (datetime(2024, 6, 15).date(), frames),
                (
                    datetime(2024, 6, 16).date(),
                    [_frame(0, flow_kw=2.0, demand_kw=1.0, price=8.0)],
                ),
            ]
        ),
        tmp_path / "peaks",
    )

    text = herding[0].read_text(encoding="utf-8")
    assert "Grid import (kW)" in text
    assert "Price (p/kWh)" in text
    assert "5.0 kW" in text
    assert herding[1].read_bytes().startswith(b"\x89PNG")
    peak_text = peaks[0].read_text(encoding="utf-8")
    assert "Peak demand (kW)" in peak_text
    assert "2024-06-15" in peak_text
    assert peaks[1].read_bytes().startswith(b"\x89PNG")
