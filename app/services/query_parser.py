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


def parse_query(q: str) -> dict | None:
    """
    Parse a plain English query string into a filter dict.

    Returns a dict of filter kwargs compatible with get_profiles(),
    or None if the query cannot be interpreted.
    """
    q = q.lower().strip()

    if not q:
        return None

    filters = {}

    if "female" in q:
        filters["gender"] = "female"
    elif "male" in q:
        filters["gender"] = "male"

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

    above_match = re.search(r"(?:above|over)\s+(\d+)", q)
    if above_match:
        filters["min_age"] = int(above_match.group(1))

    below_match = re.search(r"(?:below|under)\s+(\d+)", q)
    if below_match:
        filters["max_age"] = int(below_match.group(1))

    for country_name in sorted(COUNTRY_MAP, key=len, reverse=True):
        if country_name in q:
            filters["country_id"] = COUNTRY_MAP[country_name]
            break

    if not filters:
        return None

    return filters
