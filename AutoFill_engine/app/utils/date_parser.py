from __future__ import annotations

import re
from datetime import datetime

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
}


def parse_relative_date(text: str) -> str | None:
    next_year_match = re.search(r"\bnext\s+year\b", text, re.I)
    if next_year_match:
        return (datetime.utcnow() + relativedelta(years=1)).replace(microsecond=0).isoformat()

    match = re.search(
        r"\b(?:in|after)\s+(?:about\s+|around\s+|approximately\s+|roughly\s+)?"
        r"(\d+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)\s+"
        r"(day|days|week|weeks|month|months|year|years)\b",
        text,
        re.I,
    )
    if not match:
        return None

    amount_text = match.group(1).lower()
    amount = int(amount_text) if amount_text.isdigit() else NUMBER_WORDS[amount_text]
    unit = match.group(2).lower().rstrip("s")
    now = datetime.utcnow()

    if unit == "day":
        parsed = now + relativedelta(days=amount)
    elif unit == "week":
        parsed = now + relativedelta(weeks=amount)
    elif unit == "month":
        parsed = now + relativedelta(months=amount)
    elif unit == "year":
        parsed = now + relativedelta(years=amount)
    else:
        return None

    return parsed.replace(microsecond=0).isoformat()
