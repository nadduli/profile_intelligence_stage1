"""Rule-based natural-language query parser.

Maps free-form English (e.g. "young males from Nigeria") to a filter
dict compatible with `get_profiles()`. Deterministic, no AI/LLM.

Two phrasings of the same intent must produce the same filter dict so
that the cache (see `query_cache` + `normalize.cache_key`) treats them
as identical:

  "Nigerian females between ages 20 and 45"
  "Women aged 20-45 living in Nigeria"
                  ↓
  {gender: female, min_age: 20, max_age: 45, country_id: NG}
"""

import re

COUNTRY_MAP = {
    "nigeria": "NG",
    "ghana": "GH",
    "kenya": "KE",
    "tanzania": "TZ",
    "ethiopia": "ET",
    "uganda": "UG",
    "senegal": "SN",
    "cameroon": "CM",
    "angola": "AO",
    "mozambique": "MZ",
    "zambia": "ZM",
    "zimbabwe": "ZW",
    "malawi": "MW",
    "rwanda": "RW",
    "benin": "BJ",
    "togo": "TG",
    "mali": "ML",
    "niger": "NE",
    "chad": "TD",
    "sudan": "SD",
    "egypt": "EG",
    "morocco": "MA",
    "algeria": "DZ",
    "tunisia": "TN",
    "libya": "LY",
    "somalia": "SO",
    "eritrea": "ER",
    "djibouti": "DJ",
    "south africa": "ZA",
    "namibia": "NA",
    "botswana": "BW",
    "ivory coast": "CI",
    "burkina faso": "BF",
    "guinea": "GN",
    "sierra leone": "SL",
    "liberia": "LR",
    "gambia": "GM",
    "dr congo": "CD",
    "congo": "CG",
    "central african republic": "CF",
    "gabon": "GA",
    "cape verde": "CV",
    "comoros": "KM",
    "lesotho": "LS",
    "madagascar": "MG",
    "mauritania": "MR",
    "mauritius": "MU",
    "seychelles": "SC",
    "south sudan": "SS",
    "eswatini": "SZ",
    "western sahara": "EH",
    "equatorial guinea": "GQ",
    "guinea-bissau": "GW",
    "australia": "AU",
    "brazil": "BR",
    "canada": "CA",
    "china": "CN",
    "france": "FR",
    "germany": "DE",
    "india": "IN",
    "japan": "JP",
    "united kingdom": "GB",
    "united states": "US",
}

# Synonym groups for gender. Word boundaries (\b) prevent accidental
# matches inside unrelated tokens (e.g. "men" inside "amenable").
# `female` group is checked first because it's a strict superset of
# substrings shared with `male`.
_FEMALE_PATTERN = re.compile(
    r"\b(female|females|woman|women|lady|ladies|girl|girls)\b",
    re.IGNORECASE,
)
_MALE_PATTERN = re.compile(
    r"\b(male|males|man|men|gentleman|gentlemen|boy|boys|guy|guys)\b",
    re.IGNORECASE,
)

# Age range patterns. Order matters: more specific patterns first so the
# `\d+-\d+` fallback doesn't pre-empt structured phrasings.
_RANGE_PATTERNS: tuple[re.Pattern, ...] = (
    # "between 20 and 45" / "between ages 20 and 45" / "between 20 to 45"
    re.compile(
        r"between\s+(?:ages?\s+)?(\d{1,3})\s+(?:and|to|-)\s+(\d{1,3})",
        re.IGNORECASE,
    ),
    # "aged 20 to 45" / "ages 20 and 45"
    re.compile(
        r"\bages?\s+(\d{1,3})\s+(?:and|to|-)\s+(\d{1,3})\b",
        re.IGNORECASE,
    ),
    # "aged 20-45" / "20 to 45" / standalone "20-45"
    re.compile(
        r"(?:aged?\s+)?(?<!\d)(\d{1,3})\s*(?:-|–|to)\s*(\d{1,3})(?!\d)",
        re.IGNORECASE,
    ),
)


def _extract_age_range(q: str) -> tuple[int, int] | None:
    """Return (min_age, max_age) if any range pattern matches, else None."""
    for pat in _RANGE_PATTERNS:
        match = pat.search(q)
        if match:
            a, b = int(match.group(1)), int(match.group(2))
            return (min(a, b), max(a, b))
    return None


def parse_query(q: str) -> dict | None:
    """
    Parse a plain English query string into a filter dict.

    Returns a dict of filter kwargs compatible with get_profiles(),
    or None if the query cannot be interpreted.
    """
    q = q.lower().strip()

    if not q:
        return None

    filters: dict = {}

    # Gender — check female first (it's a strict superset risk-wise).
    if _FEMALE_PATTERN.search(q):
        filters["gender"] = "female"
    elif _MALE_PATTERN.search(q):
        filters["gender"] = "male"

    # Age range (between X and Y / X-Y / aged X to Y) takes precedence
    # over the single-bound patterns and over coarse age_group keywords,
    # because a numeric range is the most specific intent.
    age_range = _extract_age_range(q)
    if age_range is not None:
        filters["min_age"], filters["max_age"] = age_range
    else:
        # Coarse age groups — only consult when no numeric range was given.
        if "young" in q:
            filters["min_age"] = 16
            filters["max_age"] = 24
        elif "child" in q:
            filters["age_group"] = "child"
        elif "teenager" in q or "teen" in q:
            filters["age_group"] = "teenager"
        elif "adult" in q:
            filters["age_group"] = "adult"
        elif "senior" in q or "elderly" in q or "old" in q:
            filters["age_group"] = "senior"

    # Single-bound patterns. Don't override an explicit range.
    if "min_age" not in filters:
        above_match = re.search(r"(?:above|over)\s+(\d+)", q)
        if above_match:
            filters["min_age"] = int(above_match.group(1))

    if "max_age" not in filters:
        below_match = re.search(r"(?:below|under)\s+(\d+)", q)
        if below_match:
            filters["max_age"] = int(below_match.group(1))

    # Country — longest name first so "south africa" wins over "africa".
    for country_name in sorted(COUNTRY_MAP, key=len, reverse=True):
        if country_name in q:
            filters["country_id"] = COUNTRY_MAP[country_name]
            break

    if not filters:
        return None

    return filters
