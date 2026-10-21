"""Named random streams, and a ban on the global random state."""

import re
from pathlib import Path

import numpy as np
import pytest

from fleet_sim.random_streams import RandomStreams

_SRC = Path(__file__).parents[1] / "src"
# default_rng and SeedSequence build a generator. They do not touch the
# process-wide numpy state. Generator is the type of that object.
_ALLOWED_NUMPY_RANDOM = re.compile(
    r"\b(?:np|numpy)\.random\.(?:default_rng|SeedSequence|Generator)\b"
)


def test_the_same_seed_and_name_repeat_the_draws() -> None:
    first = RandomStreams(17).generator("battery").random(6)
    second = RandomStreams(17).generator("battery").random(6)

    assert np.array_equal(first, second)


def test_an_extra_stream_does_not_move_an_existing_one() -> None:
    streams = RandomStreams(17)
    battery = streams.generator("battery")
    alone = RandomStreams(17).generator("battery")
    streams.generator("demand")
    streams.generator("penetration")

    assert np.array_equal(battery.random(6), alone.random(6))


def test_two_names_are_different_streams() -> None:
    streams = RandomStreams(17)

    assert not np.array_equal(
        streams.generator("battery").random(6),
        streams.generator("demand").random(6),
    )


def test_request_order_does_not_change_a_stream() -> None:
    battery_first = RandomStreams(4)
    battery_first.generator("battery")
    demand_after = battery_first.generator("demand").random(4)

    demand_first = RandomStreams(4)
    demand_first.generator("demand")
    demand_before = demand_first.generator("demand").random(4)

    assert np.array_equal(demand_after, demand_before)


def test_sources_do_not_call_the_global_random_state() -> None:
    offenders: list[str] = []
    for path in sorted(_SRC.rglob("*.py")):
        text = _ALLOWED_NUMPY_RANDOM.sub("", path.read_text(encoding="utf-8"))
        if re.search(r"\b(?:np|numpy)\.random\b", text) or re.search(
            r"\brandom\.", text
        ):
            offenders.append(str(path.relative_to(_SRC.parent)))
    assert offenders == []


def test_seed_and_name_are_checked() -> None:
    with pytest.raises(TypeError, match="seed must be an int"):
        RandomStreams(True)
    with pytest.raises(ValueError, match="at least 0"):
        RandomStreams(-1)
    with pytest.raises(ValueError, match="must not be empty"):
        RandomStreams(0).generator("")
