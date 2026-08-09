"""Yazio API JSON Data Transformer.

Maps Yazio raw diary JSON documents into standardized DataPoint dictionaries.
Generates deterministic SHA256 idempotency_keys.

Metric names come from the shared registry
(packages/shared-schemas/src/shared_schemas/metrics.py). Two of the old names were
worse than merely inconsistent:

* ``consumed_product`` was written when an item had no calorie figure, and its value
  was then the logged *amount* -- so one series mixed grams and kilocalories. Amount
  and energy are now two metrics with two units.
* Meal aggregates were named ``f"{meal_category}_calories"``, minting a metric name
  per meal label the provider happened to use. The meal is a property of the reading,
  not a different quantity, so it lives in ``metadata["meal_category"]`` and every
  meal shares one metric.
"""

from typing import Any

from shared_schemas import idempotency_key
from shared_schemas.metrics import canonical_metric_type

from yazio_importer.config import settings

#: SHA256(tenant_id:source_id:metric_type:timestamp) — AGENTS.md rule 4, defined once
#: in `shared_schemas`. An alias rather than a wrapper: a wrapper would be a fifth
#: identical docstring to keep in step, and its `timestamp: str` annotation would hide
#: that the shared function also takes a `datetime`.
generate_idempotency_key = idempotency_key

METRIC_NUTRITION_ENERGY = canonical_metric_type("nutrition_energy")
METRIC_NUTRITION_PROTEIN = canonical_metric_type("nutrition_protein")
METRIC_NUTRITION_CARBOHYDRATES = canonical_metric_type("nutrition_carbohydrates")
METRIC_NUTRITION_FAT = canonical_metric_type("nutrition_fat")
METRIC_NUTRITION_FIBER = canonical_metric_type("nutrition_fiber")
METRIC_NUTRITION_MEAL_ENERGY = canonical_metric_type("nutrition_meal_energy")
METRIC_NUTRITION_ITEM_ENERGY = canonical_metric_type("nutrition_item_energy")
METRIC_NUTRITION_ITEM_AMOUNT = canonical_metric_type("nutrition_item_amount")
METRIC_NUTRITION_RECIPE_PORTIONS = canonical_metric_type("nutrition_recipe_portions")


def transform_consumed_items(
    raw_data: dict[str, Any] | list[Any],
    day: str,
    # No default. It used to fall back to a hardcoded workspace UUID — the one
    # `infra/db/init.sql` seeded — so a caller that forgot to pass a tenant did
    # not fail, it silently attributed somebody's food diary to that workspace.
    # The tenant now comes from the sync task, which is the only place that knows
    # it (AGENTS.md rule 2, and the hardcoded-tenant anti-pattern).
    tenant_id: str,
    source_id: str = settings.SOURCE_ID,
    product_cache: dict[str, dict[str, Any]] | None = None,
    recipe_cache: dict[str, dict[str, Any]] | None = None,
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
        pid = str(item.get("product_id", ""))
        meal_cat = item.get("daytime") or item.get("meal_category") or item.get("category") or "general"
        amount = float(item.get("amount") or item.get("quantity") or 1.0)

        p_info = product_cache.get(pid) if product_cache and pid else None
        food_name = (
            item.get("name")
            or item.get("title")
            or item.get("product_name")
            or (item.get("food") or {}).get("name")
            or (p_info.get("name") if p_info else None)
            or (f"Produkt #{pid[:8]}" if pid else "Unbekanntes Lebensmittel")
        )

        item_cal = item.get("calories") or item.get("energy") or item.get("kcal")
        item_prot = item.get("protein") or item.get("protein_g")
        item_carb = item.get("carbs") or item.get("carbs_g")
        item_fat = item.get("fat") or item.get("fat_g")

        if item_cal is None and p_info and p_info.get("energy_kcal", 0) > 0:
            base_amt = float(p_info.get("base_amount", 100.0) or 100.0)
            raw_cal = float(p_info["energy_kcal"])
            ratio = amount / base_amt
            item_cal = raw_cal * ratio
            item_prot = float(p_info.get("protein_g", 0.0)) * ratio
            item_carb = float(p_info.get("carbs_g", 0.0)) * ratio
            item_fat = float(p_info.get("fat_g", 0.0)) * ratio

        val_flt = float(item_cal) if item_cal is not None else float(amount)
        metric_type = (
            METRIC_NUTRITION_ITEM_ENERGY
            if item_cal is not None
            else METRIC_NUTRITION_ITEM_AMOUNT
        )

        if item_cal is not None:
            total_cal += float(item_cal)
            total_prot += float(item_prot or 0.0)
            total_carb += float(item_carb or 0.0)
            total_fat += float(item_fat or 0.0)

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
                "food_name": str(food_name),
                "item_id": str(item_id),
                "product_id": pid,
                "item_type": item.get("type", "product"),
                "meal_category": str(meal_cat),
                "amount": amount,
                "unit": item.get("serving") or "g",
                "calories_kcal": float(item_cal) if item_cal is not None else None,
                "protein_g": float(item_prot) if item_prot is not None else None,
                "carbs_g": float(item_carb) if item_carb is not None else None,
                "fat_g": float(item_fat) if item_fat is not None else None,
                "logged_time": item.get("date"),
            },
            "idempotency_key": idempotency_key,
            "source_type": "yazio",
        }
        data_points.append(dp)

    # 2. Transform Recipe Portions
    for idx, r_item in enumerate(recipe_portions):
        r_id = r_item.get("id") or r_item.get("recipe_id") or f"rec_{idx}"
        rid = str(r_item.get("recipe_id", ""))
        meal_cat = r_item.get("daytime") or r_item.get("meal_category") or "general"
        portion_count = r_item.get("portion_count", 1)

        cached_rname = recipe_cache.get(rid) if recipe_cache and rid else None
        recipe_name = (
            r_item.get("name")
            or r_item.get("title")
            or cached_rname
            or (f"Rezept #{rid[:8]}" if rid else "Unbekanntes Rezept")
        )

        metric_type = METRIC_NUTRITION_RECIPE_PORTIONS
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
                "food_name": str(recipe_name),
                "item_id": str(r_id),
                "recipe_id": rid,
                "item_type": "recipe_portion",
                "meal_category": str(meal_cat),
                "portion_count": portion_count,
                "logged_time": r_item.get("date"),
            },
            "idempotency_key": idempotency_key,
            "source_type": "yazio",
        }
        data_points.append(dp)

    # 3. Transform Simple Products (Custom & AI-generated meal entries)
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

        metric_type = METRIC_NUTRITION_ITEM_ENERGY
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

            metric_type = METRIC_NUTRITION_ITEM_ENERGY
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

    # 5. Daily macro summary totals
    raw_cal_val = summary.get("calories") or (total_cal if total_cal > 0 else None)
    raw_prot_val = summary.get("protein_g") or summary.get("protein") or (total_prot if total_prot > 0 else None)
    raw_carb_val = summary.get("carbs_g") or summary.get("carbohydrates") or summary.get("carbs") or (total_carb if total_carb > 0 else None)
    raw_fat_val = summary.get("fat_g") or summary.get("fat") or (total_fat if total_fat > 0 else None)
    raw_fiber_val = summary.get("fiber_g") or summary.get("fiber")

    daily_metrics = {
        METRIC_NUTRITION_ENERGY: float(raw_cal_val) if raw_cal_val is not None else None,
        METRIC_NUTRITION_PROTEIN: float(raw_prot_val) if raw_prot_val is not None else None,
        METRIC_NUTRITION_CARBOHYDRATES: float(raw_carb_val)
        if raw_carb_val is not None
        else None,
        METRIC_NUTRITION_FAT: float(raw_fat_val) if raw_fat_val is not None else None,
        METRIC_NUTRITION_FIBER: float(raw_fiber_val) if raw_fiber_val is not None else None,
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
                    metric_type = METRIC_NUTRITION_MEAL_ENERGY
                    # Every meal shares the metric now, so the meal has to enter the
                    # key instead of the name -- otherwise breakfast and dinner on one
                    # day hash identically and Core keeps whichever arrived first.
                    idempotency_key = generate_idempotency_key(
                        tenant_id, f"{source_id}_meal_{meal_cat}", metric_type, timestamp
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
