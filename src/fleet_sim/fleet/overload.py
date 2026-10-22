"""How far each transformer sits above its limit.

The numbers below are the ones a later issue computes. Until then
``day_overload`` returns zeros and the replication summary only aggregates
those zeros.
"""

from datetime import date

from fleet_sim.models.network import (
    DayOverload,
    NodeFeedback,
    ReplicationOverload,
    TransformerOverload,
)
from fleet_sim.stubs import stub


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
