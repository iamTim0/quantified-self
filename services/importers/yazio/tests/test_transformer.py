"""Unit tests for Yazio Importer Transformer.

Verifies Fizzbee Invariants:
- ExactOnceIngestion: Deterministic SHA256 idempotency_key for Yazio diary events.
- DataPointNormalization: Normalization of calories, macros, meals, and food products.
"""

import hashlib

from shared_schemas.metrics import canonical_metric_type

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
    assert "nutrition_energy" in metric_types
    assert "nutrition_protein" in metric_types
    assert "nutrition_item_energy" in metric_types

    # Every emitted name is one the registry defines -- no interpolated names, no
    # provider field names leaking into the metric space.
    assert all(canonical_metric_type(m) == m for m in metric_types)

    # The four meals share one metric and are told apart by metadata, where they used
    # to be four metric names (`breakfast_calories`, `lunch_calories`, ...). Each still
    # needs its own idempotency key, or three of the four would be dropped as
    # duplicates of the first.
    meal_dps = [dp for dp in data_points if dp["metric_type"] == "nutrition_meal_energy"]
    assert {dp["metadata"]["meal_category"] for dp in meal_dps} == {
        "breakfast",
        "lunch",
        "dinner",
        "snack",
    }
    assert len({dp["idempotency_key"] for dp in meal_dps}) == len(meal_dps)

    item_dp = next(dp for dp in data_points if dp["metric_type"] == "nutrition_item_energy")
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
    item_dp = next(dp for dp in dps if dp["metric_type"] == "nutrition_item_energy")
    assert item_dp["metadata"]["food_name"] == "Organic Almond Milk"
    assert item_dp["value"] == 100.0  # 200g of 50kcal/100g = 100kcal
