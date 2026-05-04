from __future__ import annotations

from typing import Any


EMPTY_VALUES = (None, "", [], {})


def is_present(value: Any) -> bool:
    return value not in EMPTY_VALUES


def merge_metadata(
    base_metadata: dict[str, Any] | None,
    inferred_metadata: dict[str, Any] | None,
    extracted_metadata: dict[str, Any] | None,
    overwrite_keys: set[str] | None = None,
) -> dict[str, Any]:
    merged = dict(base_metadata or {})
    overwrite_keys = overwrite_keys or set()

    sources = (
        (inferred_metadata or {}, True),
        (extracted_metadata or {}, False),
    )
    for source, allow_new_chapters in sources:
        for key, value in source.items():
            if not is_present(value):
                continue
            if key == "chapter" and isinstance(value, list):
                merged["chapter"] = _merge_chapters(
                    merged.get("chapter"),
                    value,
                    allow_new=allow_new_chapters,
                )
                continue
            if key not in overwrite_keys and is_present(merged.get(key)):
                continue
            merged[key] = value

    return merged


def _chapter_identity(chapter: dict[str, Any]) -> str | None:
    return chapter.get("uploadFile") or chapter.get("selectedVideo") or None


def _merge_chapters(
    current_value: Any,
    incoming_value: list[Any],
    allow_new: bool = False,
) -> list[Any]:
    if not isinstance(current_value, list):
        current: list[Any] = []
    else:
        current = list(current_value)

    for incoming_chapter in incoming_value:
        if not isinstance(incoming_chapter, dict):
            continue

        incoming_identity = _chapter_identity(incoming_chapter)
        matched = False

        for index, current_chapter in enumerate(current):
            if not isinstance(current_chapter, dict):
                continue
            if incoming_identity and _chapter_identity(current_chapter) == incoming_identity:
                if not is_present(current_chapter.get("chapterTitle")) and is_present(
                    incoming_chapter.get("chapterTitle")
                ):
                    current[index] = {
                        **current_chapter,
                        "chapterTitle": incoming_chapter["chapterTitle"],
                    }
                matched = True
                break

        if not matched and allow_new:
            current.append(incoming_chapter)

    return current
