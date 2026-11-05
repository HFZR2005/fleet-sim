"""Tests for Agile formula inversion and wholesale price loader."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from fleet_sim.data.agile_formula import (
    AGILE_VERSIONS,
    REGION_PARAMS,
    AgileVersion,
    apply_agile,
    best_version_for_date,
    invert_agile,
    is_peak,
    version_date_ranges,
)
from fleet_sim.data.agile_history import load_agile_rates

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_VERSION_18 = next(v for v in AGILE_VERSIONS if v.product_code == "AGILE-18-02-21")
_VERSION_22_07 = next(v for v in AGILE_VERSIONS if v.product_code == "AGILE-22-07-22")
_VERSION_24 = next(v for v in AGILE_VERSIONS if v.product_code == "AGILE-24-10-01")


def _make_api_page(rates: list[dict[str, object]]) -> bytes:
    """Build a single-page Octopus API response."""
    return json.dumps({"count": len(rates), "next": None, "results": rates}).encode()


def _rate_dict(
    valid_from: str,
    exc: float,
    inc: float | None = None,
) -> dict[str, object]:
    """Shorthand for one rate entry."""
    if inc is None:
        inc = round(exc * 1.05, 6)
    return {
        "value_exc_vat": exc,
        "value_inc_vat": inc,
        "valid_from": valid_from,
        "valid_to": None,
    }


# ---------------------------------------------------------------------------
# Formula: round-trip property
# ---------------------------------------------------------------------------


class TestRoundTrip:
    """apply_agile(invert_agile(x)) == x for uncapped slots."""

    @pytest.mark.parametrize("region", ["A", "C", "L", "P"])
    @pytest.mark.parametrize("peak", [False, True])
    def test_round_trip_uncapped(self, region: str, peak: bool) -> None:
        """Hand-worked: wholesale = 8 p/kWh, region C off-peak.

        exc = 8 × 2.00 + 0 = 16 p/kWh (well under cap 95.23).
        invert(16) = 16 / 2.00 = 8 p/kWh.
        """
        wholesale_in = 8.0
        exc, capped = apply_agile(
            wholesale_in, region=region, peak=peak, version=_VERSION_24
        )
        assert not capped
        recovered, recovered_capped = invert_agile(
            exc, region=region, peak=peak, version=_VERSION_24
        )
        assert not recovered_capped
        assert recovered == pytest.approx(wholesale_in, abs=1e-9)

    @pytest.mark.parametrize(
        "version",
        [_VERSION_18, _VERSION_22_07, _VERSION_24],
        ids=lambda v: v.product_code,
    )
    def test_round_trip_every_version(self, version: AgileVersion) -> None:
        """Round-trip works with each product version's cap."""
        wholesale_in = 5.0
        exc, capped = apply_agile(wholesale_in, region="C", peak=False, version=version)
        assert not capped
        recovered, _ = invert_agile(exc, region="C", peak=False, version=version)
        assert recovered == pytest.approx(wholesale_in, abs=1e-9)

    def test_round_trip_peak_hand_worked(self) -> None:
        """Hand-worked: wholesale = 7.4 p/kWh, region C peak.

        exc = 7.4 × 2.00 + 12 = 26.8 p/kWh.
        invert(26.8, peak) = (26.8 - 12) / 2.00 = 7.4 p/kWh.
        """
        exc, capped = apply_agile(7.4, region="C", peak=True, version=_VERSION_24)
        assert exc == pytest.approx(26.8)
        assert not capped

        recovered, _ = invert_agile(26.8, region="C", peak=True, version=_VERSION_24)
        assert recovered == pytest.approx(7.4)


# ---------------------------------------------------------------------------
# Formula: capped slot detection
# ---------------------------------------------------------------------------


class TestCapped:
    def test_capped_slot_flagged(self) -> None:
        """Wholesale above the cap triggers the capped flag.

        Hand-worked: wholesale = 50 p/kWh, region C off-peak.
        exc = min(50 × 2.00, 95.23) = min(100, 95.23) = 95.23.  Capped.
        """
        exc, capped = apply_agile(50.0, region="C", peak=False, version=_VERSION_24)
        assert capped
        assert exc == pytest.approx(95.23)

    def test_invert_detects_cap(self) -> None:
        """invert_agile flags a rate at the cap."""
        _, capped = invert_agile(95.23, region="C", peak=False, version=_VERSION_24)
        assert capped

    def test_invert_detects_cap_within_tolerance(self) -> None:
        """API rounding: 33.33 should be detected as capped for the 35p version.

        Actual cap exc VAT = 35/1.05 = 33.333…, rounded to 33.33.
        33.33 ≥ 33.33 − 0.1 = 33.23 → capped.
        """
        _, capped = invert_agile(33.33, region="C", peak=False, version=_VERSION_18)
        assert capped

    def test_uncapped_just_below_cap(self) -> None:
        """A rate well below the cap is not flagged."""
        _, capped = invert_agile(30.0, region="C", peak=False, version=_VERSION_18)
        assert not capped


# ---------------------------------------------------------------------------
# Peak detection
# ---------------------------------------------------------------------------


class TestIsPeak:
    def test_summer_bst_peak(self) -> None:
        """16:00 BST = 15:00 UTC in summer → peak."""
        stamp = datetime(2024, 6, 15, 15, 0, tzinfo=UTC)
        assert is_peak(stamp)

    def test_summer_bst_off_peak(self) -> None:
        """14:00 UTC = 15:00 BST → not peak (peak starts at 16:00 BST)."""
        stamp = datetime(2024, 6, 15, 14, 0, tzinfo=UTC)
        assert not is_peak(stamp)

    def test_winter_gmt_peak(self) -> None:
        """16:00 GMT = 16:00 UTC in winter → peak."""
        stamp = datetime(2024, 1, 15, 16, 0, tzinfo=UTC)
        assert is_peak(stamp)

    def test_winter_gmt_off_peak_after(self) -> None:
        """19:00 GMT = 19:00 UTC → not peak (peak ends at 19:00)."""
        stamp = datetime(2024, 1, 15, 19, 0, tzinfo=UTC)
        assert not is_peak(stamp)


# ---------------------------------------------------------------------------
# best_version_for_date
# ---------------------------------------------------------------------------


class TestBestVersion:
    def test_early_date_returns_oldest(self) -> None:
        assert best_version_for_date(date(2020, 6, 1)).product_code == "AGILE-18-02-21"

    def test_recent_date_returns_highest_cap(self) -> None:
        assert (
            best_version_for_date(date(2024, 10, 15)).product_code == "AGILE-24-10-01"
        )

    def test_date_before_any_product_raises(self) -> None:
        with pytest.raises(ValueError, match="no Agile product"):
            best_version_for_date(date(2017, 1, 1))

    def test_mid_range_selects_best_available(self) -> None:
        v = best_version_for_date(date(2023, 1, 1))
        assert v.product_code == "AGILE-22-08-31"


# ---------------------------------------------------------------------------
# version_date_ranges
# ---------------------------------------------------------------------------


class TestVersionDateRanges:
    def test_single_span(self) -> None:
        spans = version_date_ranges(date(2020, 1, 1), date(2020, 12, 31))
        assert len(spans) == 1
        assert spans[0][0].product_code == "AGILE-18-02-21"

    def test_span_crosses_version_boundary(self) -> None:
        spans = version_date_ranges(date(2022, 5, 1), date(2022, 9, 30))
        assert len(spans) >= 2
        codes = [s[0].product_code for s in spans]
        assert "AGILE-18-02-21" in codes or "AGILE-22-07-22" in codes


# ---------------------------------------------------------------------------
# Cross-region consistency
# ---------------------------------------------------------------------------


class TestCrossRegion:
    def test_two_regions_same_wholesale(self) -> None:
        """Inverting the same wholesale from two regions gives the same answer.

        Hand-worked: wholesale = 7 p/kWh.
        Region C off-peak: exc = 7 × 2.00 = 14.
        Region A off-peak: exc = 7 × 2.10 = 14.7.
        Invert C: 14 / 2.00 = 7.  Invert A: 14.7 / 2.10 = 7.
        """
        w = 7.0
        exc_c, _ = apply_agile(w, region="C", peak=False, version=_VERSION_24)
        exc_a, _ = apply_agile(w, region="A", peak=False, version=_VERSION_24)
        assert exc_c == pytest.approx(14.0)
        assert exc_a == pytest.approx(14.7)

        w_c, _ = invert_agile(exc_c, region="C", peak=False, version=_VERSION_24)
        w_a, _ = invert_agile(exc_a, region="A", peak=False, version=_VERSION_24)
        assert w_c == pytest.approx(w_a, abs=0.01)

    def test_cross_region_peak(self) -> None:
        """Same test during peak hours.

        wholesale = 7.4 p/kWh.
        C peak: exc = 7.4 × 2.00 + 12 = 26.8.
        A peak: exc = 7.4 × 2.10 + 13 = 28.54.
        Invert C: (26.8 − 12) / 2.00 = 7.4.
        Invert A: (28.54 − 13) / 2.10 = 7.4.
        """
        w = 7.4
        exc_c, _ = apply_agile(w, region="C", peak=True, version=_VERSION_24)
        exc_a, _ = apply_agile(w, region="A", peak=True, version=_VERSION_24)
        w_c, _ = invert_agile(exc_c, region="C", peak=True, version=_VERSION_24)
        w_a, _ = invert_agile(exc_a, region="A", peak=True, version=_VERSION_24)
        assert w_c == pytest.approx(w_a, abs=0.01)


# ---------------------------------------------------------------------------
# agile_history: load_agile_rates with injected opener
# ---------------------------------------------------------------------------


class TestAgileHistory:
    def test_load_rates_from_fixture(self, tmp_path: Path) -> None:
        """load_agile_rates with a fake opener returns parsed rates."""
        rates_data = [
            _rate_dict("2024-06-15T00:00:00Z", 14.0),
            _rate_dict("2024-06-15T00:30:00Z", 13.5),
        ]
        page = _make_api_page(rates_data)

        def opener(url: str) -> bytes:
            return page

        result = load_agile_rates(
            product="AGILE-24-10-01",
            region="C",
            period_from=datetime(2024, 6, 15, tzinfo=UTC),
            period_to=datetime(2024, 6, 16, tzinfo=UTC),
            cache_dir=tmp_path,
            opener=opener,
        )
        assert len(result) == 2
        assert result[0].value_exc_vat == 14.0
        assert result[1].value_exc_vat == 13.5

    def test_caching_avoids_second_fetch(self, tmp_path: Path) -> None:
        """After caching, the opener is not called again."""
        rates_data = [_rate_dict("2024-06-15T12:00:00Z", 20.0)]
        page = _make_api_page(rates_data)

        call_count = 0

        def opener(url: str) -> bytes:
            nonlocal call_count
            call_count += 1
            return page

        def do_load() -> None:
            load_agile_rates(
                product="AGILE-24-10-01",
                region="C",
                period_from=datetime(2024, 6, 15, tzinfo=UTC),
                period_to=datetime(2024, 6, 16, tzinfo=UTC),
                cache_dir=tmp_path,
                opener=opener,
            )

        do_load()
        assert call_count == 1

        do_load()
        assert call_count == 1


# ---------------------------------------------------------------------------
# wholesale: load_wholesale_prices integration
# ---------------------------------------------------------------------------


class TestLoadWholesalePrices:
    def _fixture_opener(self, wholesale_p: float, region: str) -> object:
        """Build an opener that returns rates for a known wholesale price."""
        params = REGION_PARAMS[region]
        rates: list[dict[str, object]] = []
        base = datetime(2024, 6, 15, tzinfo=UTC)
        for slot in range(48):
            stamp = base + timedelta(minutes=30 * slot)
            peak = is_peak(stamp)
            adder = params.peak_adder_p_per_kwh if peak else 0.0
            exc = wholesale_p * params.multiplier + adder
            rates.append(
                _rate_dict(stamp.strftime("%Y-%m-%dT%H:%M:%SZ"), round(exc, 3))
            )
        page = _make_api_page(rates)

        def opener(url: str) -> bytes:
            return page

        return opener

    def test_uncapped_prices_recovered(self, tmp_path: Path) -> None:
        """Known wholesale → apply formula → invert → same wholesale.

        Hand-worked: wholesale = 5 p/kWh = 50 GBP/MWh.
        Region C off-peak: exc = 5 × 2.00 = 10.
        Invert: 10 / 2.00 = 5 → 50 GBP/MWh.
        Peak: exc = 5 × 2.00 + 12 = 22.
        Invert peak: (22 − 12) / 2.00 = 5 → 50 GBP/MWh.
        """
        opener = self._fixture_opener(5.0, "C")
        from fleet_sim.data.wholesale import invert_rates

        inverted = invert_rates(
            region="C",
            period_from=datetime(2024, 6, 15, tzinfo=UTC),
            period_to=datetime(2024, 6, 16, tzinfo=UTC),
            cache_dir=tmp_path,
            opener=opener,
        )
        uncapped = [r for r in inverted if not r.capped]
        assert len(uncapped) == 48
        for r in uncapped:
            assert r.wholesale_gbp_per_mwh == pytest.approx(50.0, abs=0.1)

    def test_capped_slots_excluded(self, tmp_path: Path) -> None:
        """Rates at the cap are excluded from load_wholesale_prices output."""
        cap = _VERSION_18.cap_exc_vat_p_per_kwh

        rates: list[dict[str, object]] = []
        base = datetime(2020, 6, 15, tzinfo=UTC)
        for slot in range(4):
            stamp = base + timedelta(minutes=30 * slot)
            if slot < 2:
                exc = 10.0
            else:
                exc = cap
            rates.append(
                _rate_dict(stamp.strftime("%Y-%m-%dT%H:%M:%SZ"), round(exc, 3))
            )
        page = _make_api_page(rates)

        from fleet_sim.data.wholesale import invert_rates

        inverted = invert_rates(
            region="C",
            period_from=datetime(2020, 6, 15, tzinfo=UTC),
            period_to=datetime(2020, 6, 15, 2, tzinfo=UTC),
            cache_dir=tmp_path,
            opener=lambda url: page,
        )
        uncapped = [r for r in inverted if not r.capped]
        capped = [r for r in inverted if r.capped]
        assert len(uncapped) == 2
        assert len(capped) == 2


# ---------------------------------------------------------------------------
# Regression: all regions covered
# ---------------------------------------------------------------------------


def test_all_gsp_regions_have_params() -> None:
    """Every GSP region has formula parameters."""
    from fleet_sim.models.prices import GSP_REGIONS

    assert set(REGION_PARAMS) == GSP_REGIONS
