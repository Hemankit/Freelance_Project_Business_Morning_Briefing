def apply_rules(events):
    """
    v1: no filtering — just merges and sorts by urgency.
    add real filtering/deduping based on real output across both sources.
    """
    urgency_order = {"high": 0, "medium": 1, "info": 2, "low": 3}

    sorted_events = sorted(
        events,
        key=lambda e: urgency_order.get(e.get("urgency", "info"), 99)
    )

    return sorted_events