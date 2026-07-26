import hashlib
from yazio_importer.transformer import (
    generate_idempotency_key,
    transform_consumed_items,
)


def test_generate_idempotency_key():
    key = generate_idempotency_key("tenant1", "yazio", "calories", "2026-07-26T00:00:00Z")
    expected = hashlib.sha256(b"tenant1:yazio:calories:2026-07-26T00:00:00Z").hexdigest()
    assert key == expected


def test_transform_consumed_items():
    raw_data = {
        "summary": {
            "calories": 2100.0,
            "protein_g": 140.0,
            "carbs_g": 220.0,
            "fat_g": 65.0,
            "fiber_g": 30.0,
        },
        "meals": {
            "breakfast": {"calories": 500.0},
            "lunch": {"calories": 800.0},
            "dinner": {"calories": 600.0},
            "snack": {"calories": 200.0},
        },
        "items": [
            {
                "id": "item123",
                "name": "Oatmeal",
                "category": "breakfast",
                "calories": 350.0,
                "amount": 100,
                "unit": "g",
                "protein_g": 12.0,
                "carbs_g": 60.0,
                "fat_g": 5.0,
            }
        ],
    }

    data_points = transform_consumed_items(
        raw_data=raw_data,
        day="2026-07-26",
        tenant_id="tenant1",
        source_id="yazio",
    )

    assert len(data_points) >= 10
    metric_types = [dp["metric_type"] for dp in data_points]
    assert "calories" in metric_types
    assert "protein" in metric_types
    assert "breakfast_calories" in metric_types
    assert "consumed_item_calories" in metric_types

    item_dp = next(dp for dp in data_points if dp["metric_type"] == "consumed_item_calories")
    assert item_dp["metadata"]["food_name"] == "Oatmeal"
    assert len(item_dp["idempotency_key"]) == 64
