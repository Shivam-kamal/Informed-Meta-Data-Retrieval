from __future__ import annotations

import re
from datetime import datetime

from dateutil import parser as dateutil_parser
from dateutil.relativedelta import relativedelta

NUMBER_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
    "twenty one": 21,
    "twenty-two": 22,
    "twenty two": 22,
    "twenty three": 23,
    "twenty-four": 24,
    "twenty four": 24,
}


RELATIVE_DATE_PATTERN = re.compile(
    r"(?:(?:in|after|for|valid\s+for)\s+|(?:from\s+now(?:\s+is)?\s+))?"
    r"(?:about\s+|around\s+|approximately\s+|roughly\s+)?"
    r"(\d+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
    r"thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty(?:[-\s](?:one|two|three|four))?)\s+"
    r"(day|days|week|weeks|month|months|year|years)",
    re.I,
)


def current_datetime() -> datetime:
    return datetime.utcnow().replace(microsecond=0)


def parse_expiry_datetime(intent: str, now: datetime | None = None) -> str | None:
    cleaned = _clean_intent(intent)
    if not cleaned:
        return None

    base_datetime = (now or current_datetime()).replace(microsecond=0)

    parsed_relative = parse_relative_date(cleaned, now=base_datetime)
    if parsed_relative:
        return parsed_relative

    parsed_absolute = _parse_absolute_date(cleaned, base_datetime)
    if parsed_absolute:
        return parsed_absolute

    return None


def parse_relative_date(text: str, now: datetime | None = None) -> str | None:
    cleaned = re.sub(r"\s+", " ", text.strip().lower())
    base_datetime = (now or current_datetime()).replace(microsecond=0)

    if re.fullmatch(r"(?:the\s+)?(?:expiry\s+)?(?:right\s+)?now", cleaned):
        return base_datetime.isoformat()

    if re.fullmatch(r"(?:the\s+)?today", cleaned):
        return base_datetime.isoformat()

    if re.fullmatch(r"(?:the\s+)?tomorrow", cleaned):
        return (base_datetime + relativedelta(days=1)).isoformat()

    next_match = re.fullmatch(r"(?:the\s+)?next\s+(week|month|year)", cleaned)
    if next_match:
        unit = next_match.group(1)
        if unit == "week":
            return (base_datetime + relativedelta(weeks=1)).isoformat()
        if unit == "month":
            return (base_datetime + relativedelta(months=1)).isoformat()
        return (base_datetime + relativedelta(years=1)).isoformat()

    match = re.fullmatch(RELATIVE_DATE_PATTERN, cleaned)
    if not match:
        return None

    amount_text = match.group(1).lower().replace("-", " ")
    amount = int(amount_text) if amount_text.isdigit() else NUMBER_WORDS[amount_text]
    unit = match.group(2).lower().rstrip("s")

    if unit == "day":
        parsed = base_datetime + relativedelta(days=amount)
    elif unit == "week":
        parsed = base_datetime + relativedelta(weeks=amount)
    elif unit == "month":
        parsed = base_datetime + relativedelta(months=amount)
    elif unit == "year":
        parsed = base_datetime + relativedelta(years=amount)
    else:
        return None

    return parsed.isoformat()


def extract_expiry_intent(text: str) -> str | None:
    cleaned = _clean_intent(text)
    if not cleaned:
        return None

    keyword_match = re.search(
        r"(?:expiry|expiration|expires?|exp(?:iry)?\s+date(?:time)?|expDatetime|valid(?:ity)?(?:\s+for)?)"
        r"\s*(?:date\s*)?(?:is|will\s+be|should\s+be|in|after|on|at|for|:|-)?\s*"
        r"([^,.;\n]+)",
        cleaned,
        re.I,
    )
    if keyword_match:
        return _clean_intent(keyword_match.group(1))

    relative_match = RELATIVE_DATE_PATTERN.search(cleaned)
    if relative_match:
        return _clean_intent(relative_match.group(0))

    simple_match = re.search(r"\b(?:today|tomorrow|next\s+(?:week|month|year))\b", cleaned, re.I)
    if simple_match:
        return _clean_intent(simple_match.group(0))

    return None


def _clean_intent(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().strip("\"'"))


def _parse_absolute_date(text: str, base_datetime: datetime) -> str | None:
    try:
        parsed = dateutil_parser.parse(
            text,
            fuzzy=True,
            dayfirst=True,
            default=base_datetime,
        )
    except (OverflowError, ValueError, TypeError):
        return None

    return parsed.replace(microsecond=0).isoformat()
