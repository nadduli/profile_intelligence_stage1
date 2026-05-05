"""Canonicalize a parsed filter dict into a deterministic cache key.

Two requests that mean the same thing must produce the same key:
  ?gender=male&country_id=NG  ==  ?country_id=ng&gender=MALE
  /search?q=Nigerian+males    ==  /search?q=men+from+nigeria  (after parser)

The canonical form is the parsed filter dict, normalized for casing /
type / null-stripping / key order, then JSON-serialized. The same dict
always serializes to the same string. We hash that string to a fixed
length cache key.
"""

import hashlib
import json
from typing import Any

# Filter fields the parser & list endpoint can emit. Anything else is
# ignored — keeps cache keys stable if a new query param shows up that
# doesn't actually affect the SQL output.
_KNOWN_FIELDS = {
    "gender",
    "country_id",
    "age_group",
    "min_age",
    "max_age",
    "min_gender_probability",
    "min_country_probability",
    "sort_by",
    "order",
    "page",
    "limit",
}


def canonicalize(filters: dict[str, Any]) -> dict[str, Any]:
    """Return a normalized copy of `filters` suitable for hashing.

    Drops keys not in _KNOWN_FIELDS so unexpected inputs don't fragment
    the cache. Lowercases string fields. Uppercases country codes (DB
    contract). Coerces numeric fields to int/float. Drops None/empty.
    """
    out: dict[str, Any] = {}
    for key in _KNOWN_FIELDS:
        if key not in filters:
            continue
        value = filters[key]
        if value is None or value == "":
            continue

        # Type/case normalization per field
        if key == "country_id":
            out[key] = str(value).strip().upper()
        elif key in {"gender", "age_group", "sort_by", "order"}:
            out[key] = str(value).strip().lower()
        elif key in {"min_age", "max_age", "page", "limit"}:
            out[key] = int(value)
        elif key in {"min_gender_probability", "min_country_probability"}:
            out[key] = float(value)
        else:
            out[key] = value

    return out


def cache_key(filters: dict[str, Any]) -> str:
    """Deterministic cache key for a filter dict.

    Hash the JSON-serialized canonical form so the key is fixed-length
    and safe for any cache backend. We use SHA-256 because it's stdlib
    and the speed difference vs. a non-crypto hash is negligible at this
    volume.
    """
    canon = canonicalize(filters)
    encoded = json.dumps(canon, sort_keys=True, separators=(",", ":"))
    return "profiles:" + hashlib.sha256(encoded.encode()).hexdigest()[:16]
