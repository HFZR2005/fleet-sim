"""A fleet of identical homes, each with its own id."""

import pytest
from pydantic import ValidationError

from fleet_sim.fleet import Fleet, Home, identical_homes
from fleet_sim.models import BatterySpec


def _home() -> Home:
    return Home(
        home_id="home",
        region="C",
        transformer_id="tx-1",
        battery=BatterySpec(
            capacity_kwh=10.0,
            max_charge_kw=5.0,
            max_discharge_kw=5.0,
            eta_charge=0.95,
            eta_discharge=0.95,
            soc_initial=0.5,
        ),
        demand_kw=[0.3] * 48,
    )


def test_identical_homes_share_the_config_and_keep_distinct_ids() -> None:
    fleet = identical_homes(_home(), 3)

    assert [home.home_id for home in fleet.homes] == ["home-1", "home-2", "home-3"]
    for home in fleet.homes:
        assert home.region == "C"
        assert home.transformer_id == "tx-1"
        assert home.battery.capacity_kwh == 10.0
        assert home.demand_kw == [0.3] * 48
    assert fleet.homes[0].demand_kw is not fleet.homes[1].demand_kw


def test_one_home_is_a_fleet() -> None:
    fleet = identical_homes(_home(), 1)

    assert [home.home_id for home in fleet.homes] == ["home-1"]


def test_duplicate_home_ids_are_rejected() -> None:
    home = _home()
    other = home.model_copy(update={"home_id": "home"})

    with pytest.raises(ValidationError, match="duplicate home_id 'home'"):
        Fleet(homes=[home, other])


def test_n_homes_must_be_a_positive_int() -> None:
    home = _home()

    with pytest.raises(ValueError, match="at least 1"):
        identical_homes(home, 0)
    with pytest.raises(TypeError, match="must be an int"):
        identical_homes(home, True)
