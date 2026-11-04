"""How far each transformer sits above its limit.

Per-transformer per-day metrics: peak utilisation, overload energy, and
overloaded slots. Per-replication summaries across days. Hidden overloads
are slots where the fleet total is within the sum of limits but at least
one transformer is over its own. See ``docs/formulation.md``, Overload
metrics.
"""

from datetime import date

from fleet_sim.models.network import (
    DayOverload,
    NodeFeedback,
    ReplicationOverload,
    TransformerOverload,
)

_HOURS_PER_SLOT = 0.5
_SLOTS_PER_HOUR = 2


def day_overload(day: date, nodes: list[NodeFeedback]) -> DayOverload:
    """Overload totals for ``day``.

    ``nodes`` is every node from the network evaluation. The root (no limit)
    is left out of the transformer list. See ``docs/formulation.md``,
    Overload metrics.
    """
    constrained = [node for node in nodes if node.limit_kw is not None]
    if len(constrained) == 0:
        return DayOverload(
            day=day,
            transformers=[],
            hidden_overload_share=0.0,
            slot_overload_counts=[],
        )
    transformers = [_transformer_overload(node) for node in constrained]
    hidden = _hidden_overload_share(constrained)
    slot_counts = _slot_overload_counts(constrained)
    return DayOverload(
        day=day,
        transformers=transformers,
        hidden_overload_share=hidden,
        slot_overload_counts=slot_counts,
    )


def _transformer_overload(node: NodeFeedback) -> TransformerOverload:
    """Per-transformer metrics for one day.

    Peak utilisation is peak flow ÷ limit. Overload energy is the sum of
    ``overload_kw`` × Δ across slots, in kWh. Overloaded slots is the
    count of slots where flow exceeds the limit.
    See ``docs/formulation.md``, Overload metrics.
    """
    assert node.limit_kw is not None
    limit = node.limit_kw
    peak_flow = max(node.flow_kw) if node.flow_kw else 0.0
    peak_utilisation = peak_flow / limit
    overload_energy_kwh = sum(node.overload_kw) * _HOURS_PER_SLOT
    overloaded_slots = sum(1 for kw in node.overload_kw if kw > 0)
    return TransformerOverload(
        node_id=node.node_id,
        peak_utilisation=peak_utilisation,
        overload_energy_kwh=overload_energy_kwh,
        overloaded_slots=overloaded_slots,
    )


def _hidden_overload_share(constrained: list[NodeFeedback]) -> float:
    """Fraction of slots where the fleet total is under the sum of limits
    but at least one transformer is over its own.

    See ``docs/formulation.md``, Overload metrics.
    """
    if len(constrained) == 0:
        return 0.0
    n_slots = len(constrained[0].flow_kw)
    if n_slots == 0:
        return 0.0
    total_limit = sum(
        node.limit_kw for node in constrained if node.limit_kw is not None
    )
    hidden = 0
    for slot in range(n_slots):
        total_flow = sum(node.flow_kw[slot] for node in constrained)
        any_over = any(node.overload_kw[slot] > 0 for node in constrained)
        if total_flow <= total_limit and any_over:
            hidden += 1
    return hidden / n_slots


def _slot_overload_counts(constrained: list[NodeFeedback]) -> list[int]:
    """How many transformers are overloaded in each slot."""
    if len(constrained) == 0:
        return []
    n_slots = len(constrained[0].overload_kw)
    counts = [0] * n_slots
    for node in constrained:
        for slot, kw in enumerate(node.overload_kw):
            if kw > 0:
                counts[slot] += 1
    return counts


def summarise_replication(days: list[DayOverload]) -> ReplicationOverload:
    """Mean utilisation and total overload energy across ``days``.

    A transformer counts as overloaded when any of its days has an
    overloaded slot. The hour is the hour of day in which overloaded slots
    occur most, or ``None`` when no slot is overloaded.
    See ``docs/formulation.md``, Overload metrics.
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
        overload_hour=_overload_hour(days),
        hidden_overload_share=hidden,
    )


def _overload_hour(days: list[DayOverload]) -> int | None:
    """The hour of day overloaded slots occur most, or ``None``.

    Each slot maps to an hour: slot ``t`` is hour ``t // 2``. The hour
    with the highest total overload count across all days wins. Ties go
    to the earliest hour.
    """
    hour_counts: dict[int, int] = {}
    for day in days:
        for slot, count in enumerate(day.slot_overload_counts):
            if count > 0:
                hour = slot // _SLOTS_PER_HOUR
                hour_counts[hour] = hour_counts.get(hour, 0) + count
    if len(hour_counts) == 0:
        return None
    return min(hour_counts, key=lambda h: (-hour_counts[h], h))
