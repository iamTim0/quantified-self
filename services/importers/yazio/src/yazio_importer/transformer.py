"""Yazio API JSON Data Transformer.

Maps Yazio raw diary JSON documents into standardized DataPoint dictionaries.
Generates deterministic SHA256 idempotency_keys.
"""

import hashlib
from typing import Any

from yazio_importer.config import settings


def generate_idempotency_key(
    tenant_id: str, source_id: str, metric_type: str, timestamp: str
) -> str:
    """Generate a deterministic 64-character SHA256 idempotency key."""
    raw_str = f"{tenant_id}:{source_id}:{metric_type}:{timestamp}"
    return hashlib.sha256(raw_str.encode("utf-8")).hexdigest()


def transform_consumed_items(
    raw_data: dict[str, Any] | list[Any],
    day: str,
    tenant_id: str = settings.TENANT_ID,
    source_id: str = settings.SOURCE_ID,
) -> list[dict[str, Any]]:
    """Transform Yazio consumed items document for a given date into DataPoints."""
    data_points = []
    timestamp = f"{day}T00:00:00Z"

    if not raw_data:
        return data_points

    products: list[dict[str, Any]] = []
    recipe_portions: list[dict[str, Any]] = []
    simple_products: list[dict[str, Any]] = []
    items: list[dict[str, Any]] = []
    summary: dict[str, Any] = {}
    meals: dict[str, Any] = {}

    if isinstance(raw_data, list):
        products = [i for i in raw_data if isinstance(i, dict)]
    elif isinstance(raw_data, dict):
        products = raw_data.get("products") or []
        recipe_portions = raw_data.get("recipe_portions") or []
        simple_products = raw_data.get("simple_products") or []
        items = raw_data.get("items") or []
        summary = raw_data.get("summary") or raw_data.get("totals") or {}
        meals = raw_data.get("meals") or {}

    total_cal = 0.0
    total_prot = 0.0
    total_carb = 0.0
    total_fat = 0.0

    # 1. Transform Products (Logged items with product_id, amount, daytime)
    for idx, item in enumerate(products):
        item_id = item.get("id") or item.get("product_id") or f"prod_{idx}"
        meal_cat = item.get("daytime") or item.get("meal_category") or item.get("category") or "general"
        amount = item.get("amount") or item.get("quantity") or 1.0

        item_cal = item.get("calories") or item.get("energy") or item.get("kcal")
        val_flt = float(item_cal) if item_cal is not None else float(amount)

        metric_type = "consumed_item_calories" if item_cal is not None else "consumed_product"
        item_source_id = f"{source_id}_product_{item_id}"

        idempotency_key = generate_idempotency_key(
            tenant_id, item_source_id, metric_type, timestamp
        )

        dp = {
            "tenant_id": tenant_id,
            "source_id": source_id,
            "metric_type": metric_type,
            "timestamp": timestamp,
            "value": val_flt,
            "metadata": {
                "source_type": "yazio",
                "day": day,
                "item_id": str(item_id),
                "product_id": str(item.get("product_id", "")),
                "item_type": item.get("type", "product"),
                "meal_category": str(meal_cat),
                "amount": amount,
                "unit": item.get("serving") or "g",
                "serving_quantity": item.get("serving_quantity"),
                "logged_time": item.get("date"),
            },
            "idempotency_key": idempotency_key,
            "source_type": "yazio",
        }
        data_points.append(dp)

    # 2. Transform Recipe Portions
    for idx, r_item in enumerate(recipe_portions):
        r_id = r_item.get("id") or r_item.get("recipe_id") or f"rec_{idx}"
        meal_cat = r_item.get("daytime") or r_item.get("meal_category") or "general"
        portion_count = r_item.get("portion_count", 1)

        metric_type = "consumed_recipe_portion"
        item_source_id = f"{source_id}_recipe_{r_id}"

        idempotency_key = generate_idempotency_key(
            tenant_id, item_source_id, metric_type, timestamp
        )

        dp = {
            "tenant_id": tenant_id,
            "source_id": source_id,
            "metric_type": metric_type,
            "timestamp": timestamp,
            "value": float(portion_count),
            "metadata": {
                "source_type": "yazio",
                "day": day,
                "item_id": str(r_id),
                "recipe_id": str(r_item.get("recipe_id", "")),
                "item_type": "recipe_portion",
                "meal_category": str(meal_cat),
                "portion_count": portion_count,
                "logged_time": r_item.get("date"),
            },
            "idempotency_key": idempotency_key,
            "source_type": "yazio",
        }
        data_points.append(dp)

    # 3. Transform Simple Products (Custom & AI-generated meal entries with nutrients dict)
    for idx, s_item in enumerate(simple_products):
        s_id = s_item.get("id") or f"simple_{idx}"
        meal_cat = s_item.get("daytime") or s_item.get("meal_category") or "general"
        food_name = s_item.get("name", "Simple Product")
        nutrients = s_item.get("nutrients") or {}

        cal_val = nutrients.get("energy.energy") or s_item.get("calories") or s_item.get("energy") or 0.0
        prot_val = nutrients.get("nutrient.protein") or s_item.get("protein") or 0.0
        fat_val = nutrients.get("nutrient.fat") or s_item.get("fat") or 0.0
        carb_val = nutrients.get("nutrient.carb") or s_item.get("carbs") or 0.0

        total_cal += float(cal_val)
        total_prot += float(prot_val)
        total_fat += float(fat_val)
        total_carb += float(carb_val)

        metric_type = "consumed_item_calories"
        item_source_id = f"{source_id}_simple_{s_id}"

        idempotency_key = generate_idempotency_key(
            tenant_id, item_source_id, metric_type, timestamp
        )

        dp = {
            "tenant_id": tenant_id,
            "source_id": source_id,
            "metric_type": metric_type,
            "timestamp": timestamp,
            "value": float(cal_val),
            "metadata": {
                "source_type": "yazio",
                "day": day,
                "item_id": str(s_id),
                "food_name": str(food_name),
                "meal_category": str(meal_cat),
                "protein_g": float(prot_val),
                "carbs_g": float(carb_val),
                "fat_g": float(fat_val),
                "is_ai_generated": s_item.get("is_ai_generated", False),
                "logged_time": s_item.get("date"),
            },
            "idempotency_key": idempotency_key,
            "source_type": "yazio",
        }
        data_points.append(dp)

    # 4. Standard items list (legacy / fallback)
    for idx, item in enumerate(items):
        item_cal = item.get("calories") or item.get("energy") or item.get("kcal")
        food_name = item.get("name") or item.get("title") or "Unbekanntes Lebensmittel"
        item_id = item.get("id") or f"idx_{idx}"
        meal_cat = item.get("category") or item.get("meal") or "general"
        amount = item.get("amount", 100)

        p_val = float(item.get("protein_g") or item.get("protein") or 0.0)
        c_val = float(item.get("carbs_g") or item.get("carbs") or 0.0)
        f_val = float(item.get("fat_g") or item.get("fat") or 0.0)

        if item_cal is not None:
            val_flt = float(item_cal)
            total_cal += val_flt
            total_prot += p_val
            total_carb += c_val
            total_fat += f_val

            metric_type = "consumed_item_calories"
            item_source_id = f"{source_id}_{item_id}"

            idempotency_key = generate_idempotency_key(
                tenant_id, item_source_id, metric_type, timestamp
            )

            dp = {
                "tenant_id": tenant_id,
                "source_id": source_id,
                "metric_type": metric_type,
                "timestamp": timestamp,
                "value": val_flt,
                "metadata": {
                    "source_type": "yazio",
                    "day": day,
                    "item_id": str(item_id),
                    "food_name": str(food_name),
                    "meal_category": str(meal_cat),
                    "amount": amount,
                    "unit": item.get("unit", "g"),
                    "protein_g": p_val,
                    "carbs_g": c_val,
                    "fat_g": f_val,
                },
                "idempotency_key": idempotency_key,
                "source_type": "yazio",
            }
            data_points.append(dp)

    # 5. Daily macro summary totals (from Yazio summary object or aggregated sum)
    daily_metrics = {
        "calories": summary.get("calories") or (total_cal if total_cal > 0 else None),
        "protein": summary.get("protein_g") or summary.get("protein") or (total_prot if total_prot > 0 else None),
        "carbohydrates": summary.get("carbs_g") or summary.get("carbohydrates") or summary.get("carbs") or (total_carb if total_carb > 0 else None),
        "fat": summary.get("fat_g") or summary.get("fat") or (total_fat if total_fat > 0 else None),
        "fiber": summary.get("fiber_g") or summary.get("fiber"),
    }

    for metric_type, val in daily_metrics.items():
        if val is None:
            continue

        idempotency_key = generate_idempotency_key(
            tenant_id, source_id, metric_type, timestamp
        )

        dp = {
            "tenant_id": tenant_id,
            "source_id": source_id,
            "metric_type": metric_type,
            "timestamp": timestamp,
            "value": float(val),
            "metadata": {
                "source_type": "yazio",
                "day": day,
            },
            "idempotency_key": idempotency_key,
            "source_type": "yazio",
        }
        data_points.append(dp)

    # 6. Meal category aggregates
    if isinstance(meals, dict):
        for meal_cat, meal_info in meals.items():
            if isinstance(meal_info, dict) and ("calories" in meal_info or "energy" in meal_info):
                cal_val = meal_info.get("calories") or meal_info.get("energy")
                if cal_val is not None:
                    metric_type = f"{meal_cat}_calories"
                    idempotency_key = generate_idempotency_key(
                        tenant_id, source_id, metric_type, timestamp
                    )
                    dp = {
                        "tenant_id": tenant_id,
                        "source_id": source_id,
                        "metric_type": metric_type,
                        "timestamp": timestamp,
                        "value": float(cal_val),
                        "metadata": {
                            "source_type": "yazio",
                            "day": day,
                            "meal_category": meal_cat,
                        },
                        "idempotency_key": idempotency_key,
                        "source_type": "yazio",
                    }
                    data_points.append(dp)

    return data_points
