"""How far each transformer sits above its limit.

The numbers below are the ones a later issue computes. Until then
``day_overload`` returns zeros and the replication summary only aggregates
those zeros.
"""

from datetime import date

from pydantic import BaseModel, ConfigDict

from fleet_sim.fleet.network import NodeFeedback
from fleet_sim.stubs import stub


class TransformerOverload(BaseModel):
    """One transformer on one day."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    node_id: str
    peak_utilisation: float
    overload_energy_kwh: float
    overloaded_slots: int


class DayOverload(BaseModel):
    """Every transformer on one civil day, plus the hidden-overload share.

    The hidden-overload share is the fraction of slots where the fleet total
    is inside the sum of the limits but at least one transformer is over its
    own.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    day: date
    transformers: list[TransformerOverload]
    hidden_overload_share: float


class ReplicationOverload(BaseModel):
    """The day's overloads, reduced to one replication.

    ``overload_hour`` is the hour of day in which overloaded slots occur
    most. It is ``None`` when no slot is overloaded.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    transformers_overloaded_share: float
    mean_peak_utilisation: float
    worst_peak_utilisation: float
    total_overload_energy_kwh: float
    overload_hour: int | None
    hidden_overload_share: float


@stub("overload metrics are zero")
def day_overload(day: date, nodes: list[NodeFeedback]) -> DayOverload:
    """Placeholder overload totals for ``day``.

    Every transformer in ``nodes`` is reported as unused. The root, which
    has no limit, is left out.
    """
    transformers = [
        TransformerOverload(
            node_id=node.node_id,
            peak_utilisation=0.0,
            overload_energy_kwh=0.0,
            overloaded_slots=0,
        )
        for node in nodes
        if node.limit_kw is not None
    ]
    return DayOverload(day=day, transformers=transformers, hidden_overload_share=0.0)


def summarise_replication(days: list[DayOverload]) -> ReplicationOverload:
    """Mean utilisation and total overload energy across ``days``.

    A transformer counts as overloaded when any of its days has an
    overloaded slot. The hour is left unset when that never happens.
    """
    if len(days) == 0:
        raise ValueError("days must contain at least one day")
    by_transformer: dict[str, list[TransformerOverload]] = {}
    for day in days:
        for item in day.transformers:
            by_transformer.setdefault(item.node_id, []).append(item)
    if len(by_transformer) == 0:
        raise ValueError("days must name at least one transformer")
    overloaded = 0
    utilisations: list[float] = []
    energy = 0.0
    for records in by_transformer.values():
        if any(record.overloaded_slots > 0 for record in records):
            overloaded += 1
        utilisations.extend(record.peak_utilisation for record in records)
        energy += sum(record.overload_energy_kwh for record in records)
    hidden = sum(day.hidden_overload_share for day in days) / len(days)
    return ReplicationOverload(
        transformers_overloaded_share=overloaded / len(by_transformer),
        mean_peak_utilisation=sum(utilisations) / len(utilisations),
        worst_peak_utilisation=max(utilisations),
        total_overload_energy_kwh=energy,
        overload_hour=None,
        hidden_overload_share=hidden,
    )
