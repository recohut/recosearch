from recosearch.semantic_layers.context.events import EventBus, MetadataChanged, affected_terms_for_ref, get_event_bus


def test_event_bus_schema_change_marks_drift():
    bus = EventBus()
    bus.publish(MetadataChanged(kind="schema-change", ref="metric:novashop:order_revenue"))
    assert "schema_changed" in bus.drift_reasons("metric:novashop:order_revenue")


def test_policy_change_event():
    bus = EventBus()
    bus.publish(MetadataChanged(kind="policy-change", ref="policy_rules"))
    assert "policy_changed" in bus.drift_reasons("policy_rules")


def test_affected_terms_for_metric_ref():
    term_map = {
        "term:novashop:revenue": ("metric:novashop:order_revenue",),
        "term:novashop:customer": ("entity:novashop:customer",),
    }
    affected = affected_terms_for_ref("metric:novashop:order_revenue", term_metric_map=term_map)
    assert "term:novashop:revenue" in affected
    assert "term:novashop:customer" not in affected


def test_event_bus_marks_affected_terms_and_queues_recert():
    bus = EventBus()
    event = MetadataChanged(kind="schema-change", ref="metric:novashop:order_revenue")
    affected = bus.mark_affected_terms(
        event,
        term_ref_map={
            "term:novashop:revenue": ("metric:novashop:order_revenue",),
            "term:novashop:customer": ("entity:novashop:customer",),
        },
    )
    assert affected == ("term:novashop:revenue",)
    assert "schema_changed" in bus.drift_reasons("term:novashop:revenue")
    assert bus.queued_recertifications() == ("term:novashop:revenue",)


def test_re_cert_subscriber():
    bus = EventBus()
    seen: list[str] = []

    def handler(event: MetadataChanged) -> None:
        seen.append(event.kind)

    bus.subscribe(handler)
    bus.publish(MetadataChanged(kind="catalog-update", ref="term:novashop:revenue"))
    assert seen == ["catalog-update"]


def test_global_bus_clear():
    bus = get_event_bus()
    bus.clear()
    bus.publish(MetadataChanged(kind="freshness-breach", ref="novashop"))
    assert bus.drift_reasons("novashop")
    bus.clear()
    assert bus.drift_reasons("novashop") == ()
