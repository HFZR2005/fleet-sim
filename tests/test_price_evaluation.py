"""Tests for scoring fitted price curves and the fleet weights they use."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from fleet_sim.data.settlement import settlement_periods_utc
from fleet_sim.data.source import PriceSource
from fleet_sim.models.frames import Frame, HomeFrame
from fleet_sim.models.prices import PriceSeries, london_day_bounds_utc
from fleet_sim.models.scenario import Scenario
from fleet_sim.prices.curves import Cubic, CubicFit, CubicOffsetFit, FittedCurve
from fleet_sim.prices.dataset import PriceDataset, PriceObservation
from fleet_sim.prices.evaluation import (
    Bracket,
    EvaluationReport,
    FitResult,
    bracket,
    comparison_table,
    evaluate,
    residuals,
)
from fleet_sim.prices.fleet_weights import FleetCharging, fleet_charging
from fleet_sim.prices.targets import TARGETS

_ROOT = Path(__file__).resolve().parents[1]
# 15 June 2024 is BST: slot i starts at London 00:00 + 30·i minutes.
_SLOTS = settlement_periods_utc(date(2024, 6, 15))


def _observation(
    i: int,
    load: float,
    price: float,
    *,
    cost: float = 1.0,
    censored: bool = False,
    upper: float | None = None,
) -> PriceObservation:
    stamp = _SLOTS[i]
    return PriceObservation(
        settlement_start=stamp,
        wholesale_price_gbp_per_mwh=price,
        censored=censored,
        wholesale_upper_gbp_per_mwh=upper,
        residual_load_gw=load,
        fuel_cost_gbp_per_mwh=cost,
        year=stamp.year,
    )


@pytest.fixture
def five_slots() -> PriceDataset:
    """Five consecutive slots; slot 2 is censored.  h(R) = R³ gives:

    slot  London  R    π       h(R)     e = π − h
    0     00:00   1    2       1        1
    1     00:30   2    8       8        0
    2     01:00   2    10 (≥)  –        –
    3     01:30   3    25      27       −2
    4     02:00   3.5  43.875  42.875   1
    """
    rows = [(1.0, 2.0), (2.0, 8.0), (2.0, 10.0), (3.0, 25.0), (3.5, 43.875)]
    return PriceDataset(
        observations=[
            _observation(i, load, price, censored=i == 2)
            for i, (load, price) in enumerate(rows)
        ],
        drops=[],
    )


@pytest.fixture
def charging() -> FleetCharging:
    """The fleet charges 2 kW in slot 0 and discharges 3 and 1 kW in 2 and 3."""
    return FleetCharging(
        scenario="test.toml",
        start=date(2024, 6, 15),
        end=date(2024, 6, 15),
        slot_start_utc=[_SLOTS[0], _SLOTS[2], _SLOTS[3]],
        net_battery_kw=[2.0, -3.0, -1.0],
        skipped_days=[],
    )


def _evaluate(
    fitted: FittedCurve, data: PriceDataset, charging: FleetCharging
) -> FitResult:
    return evaluate(
        fitted,
        data,
        data,
        TARGETS["raw_pooled"],
        charging,
        model_name="raw_pooled/cubic",
        curve_family="cubic",
        target_name="raw_pooled",
        split="in-sample",
    )


def test_evaluate_hand_worked(
    five_slots: PriceDataset, charging: FleetCharging
) -> None:
    """h(R) = R³, h′(R) = 3R², raw target (k = 1).

    Level, exact slots only: e = [1, 0, −2, 1].
      RMSE = √(6/4) = 1.224745, all in JJA.
      By London hour: 0 → √((1 + 0)/2) = 0.707107, 1 → 2, 2 → 1.
    Slope pairs (slot 2 is censored, so only 0→1 and 3→4):
      0→1: Δπ = 6, predicted h′(1)·ΔR = 3·1 = 3, error 3.
      3→4: Δπ = 18.875, predicted h′(3)·ΔR = 27·0.5 = 13.5, error 5.375.
      RMSE = √((9 + 28.890625)/2) = 4.352621.
    Charging: w = 2 at slot 0.  Pair 0→1 error 3, so RMSE 3; mean slope
      h′(1) = 3.
    Discharging: w = 3 at slot 2 and 1 at slot 3, total 4.  Mean slope
      (3·h′(2) + 1·h′(3))/4 = (36 + 27)/4 = 15.75, censored slot 2
      included.  Only pair 3→4 is weighted, so RMSE 5.375.
    Sanity over R ∈ [1, 3.5]: min slope h′(1) = 3; h(3.5) = 42.875,
      h′(3.5) = 36.75.
    """
    result = _evaluate(CubicFit(a=1.0, sigma=1.0), five_slots, charging)

    assert result.year == 2024
    assert result.exact_slots == 4
    assert result.rmse_gbp_per_mwh == pytest.approx(1.224745, abs=1e-6)
    assert result.rmse_by_season_gbp_per_mwh == {
        "JJA": pytest.approx(1.224745, abs=1e-6)
    }
    assert result.rmse_by_hour_gbp_per_mwh == pytest.approx(
        {0: 0.707107, 1: 2.0, 2: 1.0}, abs=1e-6
    )
    assert result.slope_pairs == 2
    assert result.slope_rmse_gbp_per_mwh == pytest.approx(4.352621, abs=1e-6)
    assert result.charging.weight_kw == 2.0
    assert result.charging.slope_rmse_gbp_per_mwh == pytest.approx(3.0)
    assert result.charging.mean_slope_gbp_per_mwh_per_gw == pytest.approx(3.0)
    assert result.discharging.weight_kw == 4.0
    assert result.discharging.slope_rmse_gbp_per_mwh == pytest.approx(5.375)
    assert result.discharging.mean_slope_gbp_per_mwh_per_gw == pytest.approx(15.75)
    assert result.sanity.min_slope == pytest.approx(3.0)
    assert result.sanity.value_at_r_max == pytest.approx(42.875)
    assert result.sanity.slope_at_r_max == pytest.approx(36.75)


def test_comparison_table_flags_a_falling_curve_and_shows_the_spread(
    five_slots: PriceDataset, charging: FleetCharging
) -> None:
    """Two families on the same target and year.

    h = R³ has mean slopes 3 (charging) and 15.75 (discharging), above.
    h = −R + 0.01·R³ has h′ = −1 + 0.03R²:
      charging h′(1) = −0.97;
      discharging (3·h′(2) + h′(3))/4 = (3·(−0.88) + (−0.73))/4 = −0.8425.
    Spreads: 3 − (−0.97) = 3.97 and 15.75 − (−0.8425) = 16.5925.
    h′(1) < 0, so the second row is flagged.  Brackets for 2021 get a
    table of their own, ahead of the other years.
    """
    falling = CubicOffsetFit(a0=0.0, a1=-1.0, a3=0.01, sigma=1.0)
    brackets = [
        Bracket(
            model_name="raw_pooled/cubic",
            curve_family="cubic",
            target_name="raw_pooled",
            year=year,
            method="censored",
            censored_slots=10,
            r95_gw=30.0,
            slope_at_r95=2.5,
            parameters={"a": 0.001, "sigma": 50.0},
        )
        for year in (2024, 2021)
    ]
    report = EvaluationReport(
        results=[
            _evaluate(CubicFit(a=1.0, sigma=1.0), five_slots, charging),
            _evaluate(falling, five_slots, charging),
        ],
        brackets=brackets,
    )

    table = comparison_table(report)

    rows = [line for line in table.splitlines() if line.startswith("| raw_pooled/")]
    assert "| RMSE (exact) |" in table
    assert "⚠" not in rows[0]
    assert "⚠ |" in rows[1]
    assert "| raw_pooled | 2024 | 3.97 | 16.59 |" in table
    row_2021 = (
        "| raw_pooled/cubic | 2021 | 10 | censored | 30 | 2.5 | a=0.001, sigma=50 |"
    )
    assert table.index("### 2021") < table.index(row_2021)
    assert table.index(row_2021) < table.index("### Other years")
    assert table.index("### Other years") < table.index(
        "| raw_pooled/cubic | 2024 | 10"
    )


def test_evaluate_scores_censored_slots_by_hand() -> None:
    """h(R) = R³ with σ = 2, raw target.  One slot of each kind at h = 0.

    slot  R  bounds on π   z                log-likelihood
    0     1  1 (exact)     (1 − 1)/2 = 0    −½·log 2π − log 2 = −1.61209
    1     0  0 (exact)     0                −1.61209
    2     0  [1, ∞)        P(Z ≥ 0.5)       log 0.308538 = −1.17591
    3     0  [−2, 2]       P(−1 ≤ Z ≤ 1)    log 0.682689 = −0.38172
    Mean over 4 slots: −4.78181 / 4 = −1.19545.
    Hit rate: slot 2 predicts 0 < 1, a miss; slot 3 predicts 0 ∈ [−2, 2],
    a hit.  1 of 2.
    """
    data = PriceDataset(
        observations=[
            _observation(0, 1.0, 1.0),
            _observation(1, 0.0, 0.0),
            _observation(2, 0.0, 1.0, censored=True),
            _observation(3, 0.0, -2.0, censored=True, upper=2.0),
        ],
        drops=[],
    )
    no_fleet = FleetCharging(
        scenario="test.toml",
        start=date(2024, 6, 15),
        end=date(2024, 6, 15),
        slot_start_utc=[],
        net_battery_kw=[],
        skipped_days=[],
    )

    result = _evaluate(CubicFit(a=1.0, sigma=2.0), data, no_fleet)

    assert result.censored_slots == 2
    assert result.log_likelihood_per_slot == pytest.approx(-1.19545, abs=1e-5)
    assert result.hit_rate == pytest.approx(0.5)


def test_bracket_fits_one_year_three_ways() -> None:
    """Cubic a·R³ on four slots; slot 2 is censored, π ≥ 4.

    R = [1, 2, 2, 1], π = [1, 8, ≥4, 2].
    dropped:     â = Σ πR³ / Σ R⁶ = (1 + 64 + 2) / (1 + 64 + 1) = 67/66
    lower_bound: â = (67 + 4·8) / (66 + 64) = 99/130
    censored:    π ≥ 4 is only a floor, so â rises above 99/130.
    R95 of [1, 1, 2, 2] (linear interpolation) is 2, so the slope there
    is 3â·2² = 12â.
    """
    data = PriceDataset(
        observations=[
            _observation(0, 1.0, 1.0),
            _observation(1, 2.0, 8.0),
            _observation(2, 2.0, 4.0, censored=True),
            _observation(3, 1.0, 2.0),
        ],
        drops=[],
    )

    rows = bracket(
        Cubic(),
        data,
        TARGETS["raw_pooled"],
        model_name="raw_pooled/cubic",
        curve_family="cubic",
        target_name="raw_pooled",
    )

    by_method = {row.method: row for row in rows}
    assert by_method.keys() == {"dropped", "lower_bound", "censored"}
    assert by_method["dropped"].parameters["a"] == pytest.approx(67 / 66)
    assert by_method["lower_bound"].parameters["a"] == pytest.approx(99 / 130)
    assert by_method["censored"].parameters["a"] > 99 / 130
    for row in rows:
        assert row.censored_slots == 1
        assert row.r95_gw == pytest.approx(2.0)
        assert row.slope_at_r95 == pytest.approx(12 * row.parameters["a"])


def test_residuals_on_the_fuel_adjusted_target() -> None:
    """ε = π − k·h(R) with h(R) = R³, exact slots only.

    Slot 0: 50 − 25·1 = 25.  Slot 1: 200 − 20·8 = 40.  Slot 2 is censored.
    """
    data = PriceDataset(
        observations=[
            _observation(0, 1.0, 50.0, cost=25.0),
            _observation(1, 2.0, 200.0, cost=20.0),
            _observation(2, 2.0, 300.0, cost=20.0, censored=True),
        ],
        drops=[],
    )

    result = residuals(CubicFit(a=1.0, sigma=0.0), data, TARGETS["fuel_adjusted"])

    assert [r.settlement_start for r in result] == _SLOTS[:2]
    assert [r.residual_gbp_per_mwh for r in result] == pytest.approx([25.0, 40.0])


class _FlatPrices:
    """A flat 10 p/kWh every day; clock-change days raise as Agile does."""

    def load(self, day: date, region: str) -> PriceSeries:
        start, _end = london_day_bounds_utc(day)
        return PriceSeries(
            region=region,
            day=day,
            timestamps_utc=[start + timedelta(minutes=30) * i for i in range(48)],
            price_p_per_kwh=[10.0] * 48,
        )


def _home(home_id: str, import_kw: float, demand_kw: float) -> HomeFrame:
    return HomeFrame(
        home_id=home_id,
        transformer_id=None,
        soc=0.5,
        mode="idle",
        import_kw=import_kw,
        demand_kw=demand_kw,
    )


def test_fleet_charging_skips_clock_changes_and_is_cached(tmp_path: Path) -> None:
    """30 March to 1 April 2024; the clocks go forward on 31 March.

    So the fleet is solved twice, once for each side of the change.  The
    fake solver gives one frame per run, with two homes:
    net = (3 − 1) + (0 − 1) = 1 kW.  A second call reads the cache.
    """
    scenario = tmp_path / "identical.toml"
    scenario.write_bytes((_ROOT / "scenarios" / "identical.toml").read_bytes())
    runs: list[tuple[date, date]] = []

    def simulate(run: Scenario, prices: PriceSource) -> list[Frame]:
        runs.append((run.start, run.end))
        stamp = prices.load(run.start, run.region).timestamps_utc[0]
        homes = [_home("a", 3.0, 1.0), _home("b", 0.0, 1.0)]
        return [Frame(slot_start=stamp, price_p_per_kwh=10.0, homes=homes, nodes=[])]

    def load() -> FleetCharging:
        return fleet_charging(
            scenario,
            date(2024, 3, 30),
            date(2024, 4, 1),
            price_source=_FlatPrices(),
            cache_dir=tmp_path,
            simulate=simulate,
        )

    first = load()
    second = load()

    assert runs == [
        (date(2024, 3, 30), date(2024, 3, 30)),
        (date(2024, 4, 1), date(2024, 4, 1)),
    ]
    assert first.skipped_days == [date(2024, 3, 31)]
    assert first.slot_start_utc == [
        datetime(2024, 3, 30, tzinfo=UTC),
        datetime(2024, 3, 31, 23, tzinfo=UTC),
    ]
    assert first.net_battery_kw == [1.0, 1.0]
    assert second == first
