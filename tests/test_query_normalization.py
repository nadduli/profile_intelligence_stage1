"""Stage 4b — query normalization invariants.

Two equivalent natural-language queries must produce:
  1. the same parsed filter dict
  2. the same canonical cache key

These tests pin the spec's two example phrasings together with a few
common variants so a future parser regression is caught.
"""

from app.services.normalize import cache_key, canonicalize
from app.services.query_parser import parse_query


def test_spec_example_phrasings_collapse_to_same_filters():
    """Spec: 'Nigerian females between ages 20 and 45' must equal
    'Women aged 20-45 living in Nigeria'.
    """
    a = parse_query("Nigerian females between ages 20 and 45")
    b = parse_query("Women aged 20-45 living in Nigeria")

    expected = {
        "gender": "female",
        "country_id": "NG",
        "min_age": 20,
        "max_age": 45,
    }
    assert a == expected
    assert b == expected


def test_spec_example_phrasings_share_cache_key():
    """The whole point of normalization — same dict, same key."""
    a = parse_query("Nigerian females between ages 20 and 45")
    b = parse_query("Women aged 20-45 living in Nigeria")
    assert cache_key(a) == cache_key(b)


def test_men_synonyms_resolve_to_male():
    for phrasing in ("men from kenya", "guys from kenya", "boys from kenya"):
        result = parse_query(phrasing)
        assert result is not None
        assert result["gender"] == "male"
        assert result["country_id"] == "KE"


def test_women_synonyms_resolve_to_female():
    for phrasing in (
        "women from senegal",
        "ladies from senegal",
        "girls from senegal",
    ):
        result = parse_query(phrasing)
        assert result is not None
        assert result["gender"] == "female"
        assert result["country_id"] == "SN"


def test_word_boundary_prevents_accidental_synonym_match():
    """`men` inside `amenable` must not match. Same for `man` inside
    a country name like 'oman' if it were ever added."""
    # 'amenable' is contrived, but proves the principle
    result = parse_query("we should be amenable here")
    assert result is None or "gender" not in result


def test_range_patterns_all_collapse_equally():
    """Multiple ways to write the same age range produce the same key."""
    phrasings = [
        "females between 20 and 45 in nigeria",
        "females between ages 20 and 45 in nigeria",
        "females aged 20 to 45 in nigeria",
        "females aged 20-45 in nigeria",
        "females ages 20 and 45 in nigeria",
    ]
    keys = [cache_key(parse_query(p)) for p in phrasings]
    assert len(set(keys)) == 1, f"Expected one canonical key, got: {keys}"


def test_canonicalize_strips_unknown_fields():
    """Normalization drops keys that aren't in the allowlist."""
    canon = canonicalize({"gender": "female", "foo": "bar", "page": None})
    assert "foo" not in canon
    assert "page" not in canon  # None values are dropped
    assert canon["gender"] == "female"


def test_canonicalize_normalizes_case():
    a = canonicalize({"gender": "MALE", "country_id": "ng"})
    b = canonicalize({"gender": "male", "country_id": "NG"})
    assert a == b
