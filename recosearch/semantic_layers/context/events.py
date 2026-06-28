from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

EVENT_KINDS = frozenset(
    {"schema-change", "policy-change", "freshness-breach", "catalog-update"}
)


@dataclass(frozen=True, slots=True)
class MetadataChanged:
    kind: str
    ref: str


@dataclass
class EventBus:
    """In-process active metadata bus (DataHub MCL pattern, no Kafka)."""

    _subscribers: list[Callable[[MetadataChanged], None]] = field(default_factory=list)
    _drift_markers: dict[str, list[str]] = field(default_factory=dict)
    _re_cert_queue: list[str] = field(default_factory=list)

    def subscribe(self, handler: Callable[[MetadataChanged], None]) -> None:
        self._subscribers.append(handler)

    def publish(self, event: MetadataChanged) -> None:
        if event.kind not in EVENT_KINDS:
            raise ValueError(f"unknown event kind: {event.kind}")
        for handler in self._subscribers:
            handler(event)
        self._drift_markers.setdefault(event.ref, []).append(event.kind)

    def drift_reasons(self, ref: str) -> tuple[str, ...]:
        kinds = self._drift_markers.get(ref, [])
        reasons: list[str] = []
        if "schema-change" in kinds:
            reasons.append("schema_changed")
        if "policy-change" in kinds:
            reasons.append("policy_changed")
        if "freshness-breach" in kinds:
            reasons.append("stale_data")
        if "catalog-update" in kinds:
            reasons.append("catalog_updated")
        return tuple(sorted(set(reasons)))

    def clear(self) -> None:
        self._subscribers.clear()
        self._drift_markers.clear()
        self._re_cert_queue.clear()

    def enqueue_re_cert(self, term_id: str) -> None:
        if term_id not in self._re_cert_queue:
            self._re_cert_queue.append(term_id)

    def queued_recertifications(self) -> tuple[str, ...]:
        return tuple(self._re_cert_queue)

    def mark_affected_terms(
        self,
        event: MetadataChanged,
        *,
        term_ref_map: dict[str, tuple[str, ...]],
    ) -> tuple[str, ...]:
        affected = affected_terms_for_ref(event.ref, term_metric_map=term_ref_map)
        for term_id in affected:
            self._drift_markers.setdefault(term_id, []).append(event.kind)
            self.enqueue_re_cert(term_id)
        return tuple(affected)


_GLOBAL_BUS = EventBus()


def get_event_bus() -> EventBus:
    return _GLOBAL_BUS


def subscribe_re_cert(handler: Callable[[MetadataChanged], None]) -> None:
    """Register a handler that enqueues re-certification on metadata change."""
    _GLOBAL_BUS.subscribe(handler)


def affected_terms_for_ref(
    ref: str,
    *,
    term_metric_map: dict[str, tuple[str, ...]],
) -> list[str]:
    affected: list[str] = []
    for term_id, metric_refs in term_metric_map.items():
        if term_id == ref or ref in metric_refs:
            affected.append(term_id)
    return affected
