"""Unit tests for Yazio Importer Transformer.

Verifies Fizzbee Invariants:
- ExactOnceIngestion: Deterministic SHA256 idempotency_key for Yazio diary events.
- DataPointNormalization: Normalization of calories, macros, meals, and food products.
"""

import hashlib

from yazio_importer.transformer import (
    generate_idempotency_key,
    transform_consumed_items,
)


def test_generate_idempotency_key():
    """Verifies Fizzbee Invariant: ExactOnceIngestion (Deterministic Key)."""
    key = generate_idempotency_key("tenant1", "yazio", "calories", "2026-07-26T00:00:00Z")
    expected = hashlib.sha256(b"tenant1:yazio:calories:2026-07-26T00:00:00Z").hexdigest()
    assert key == expected
    assert len(key) == 64


def test_transform_consumed_items():
    """Verifies transformation of Yazio diary summary and consumed items into DataPoints."""
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


def test_transform_consumed_items_with_caches():
    """Verifies product and recipe cache resolution during transformation."""
    raw_data = {
        "products": [
            {
                "id": "item_p1",
                "product_id": "prod_1",
                "amount": 200,
                "category": "lunch",
            }
        ]
    }
    product_cache = {
        "prod_1": {
            "name": "Organic Almond Milk",
            "base_amount": 100.0,
            "energy_kcal": 50.0,
            "protein_g": 2.0,
            "carbs_g": 3.0,
            "fat_g": 4.0,
        }
    }

    dps = transform_consumed_items(
        raw_data=raw_data,
        day="2026-07-31",
        tenant_id="t1",
        source_id="s1",
        product_cache=product_cache,
    )

    assert len(dps) > 0
    item_dp = next(dp for dp in dps if dp["metric_type"] == "consumed_item_calories")
    assert item_dp["metadata"]["food_name"] == "Organic Almond Milk"
    assert item_dp["value"] == 100.0  # 200g of 50kcal/100g = 100kcal
