from typing import Any

from app.config.field_config import FIELD_CONFIG


def get_missing_required_fields(metadata: dict[str, Any]) -> list[str]:
    missing_fields: list[str] = []

    for field in FIELD_CONFIG["required"]:
        value = metadata.get(field)
        if value is None or value == "" or value == [] or value == {}:
            missing_fields.append(field)

    return missing_fields
