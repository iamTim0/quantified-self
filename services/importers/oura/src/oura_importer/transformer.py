import hashlib
import json
from typing import List, Dict, Any
from oura_importer.config import settings

def _generate_idempotency_key(tenant_id: str, source_id: str, metric_type: str, timestamp: str) -> str:
    key_str = f"{tenant_id}:{source_id}:{metric_type}:{timestamp}"
    return hashlib.sha256(key_str.encode()).hexdigest()

def transform_sleep_data(raw_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    # Transform Oura API responses into the standardized DataPoint schema
    data_points = []
    
    for item in raw_data.get("data", []):
        timestamp = item.get("day")
        metric_type = "sleep_score"
        value = item.get("score")
        
        idempotency_key = _generate_idempotency_key(
            settings.TENANT_ID, settings.SOURCE_ID, metric_type, timestamp
        )
        
        dp = {
            "tenant_id": settings.TENANT_ID,
            "source_id": settings.SOURCE_ID,
            "metric_type": metric_type,
            "timestamp": timestamp,
            "value": value,
            "metadata": item,
            "idempotency_key": idempotency_key
        }
        data_points.append(dp)
        
    return data_points
