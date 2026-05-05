"""upload csv file data"""

import argparse
import csv
import os
import random
from pathlib import Path


COLUMNS = [
    "name", "gender", "gender_probability", "age", "age_group",
    "country_id", "country_name", "country_probability"
]

COUNTRIES = [
    ("NG", "Nigeria"), ("KE", "Kenya"), ("ZA", "South Africa"),
    ("UG", "Uganda"), ("GH", "Ghana"), ("TZ", "Tanzania"),
    ("ET", "Ethiopia"), ("RW", "Rwanda"), ("SN", "Senegal"),
    ("US", "United States"), ("GB", "United Kingdom"),
    ("IN", "India"), ("BR", "Brazil"),
]

FIRST_NAMES = [
    "Amara", "Kwame", "Fatima", "Tunde", "Aisha", "Kofi",
    "Zara", "Emeka", "Nia", "Jabari", "Imani", "Sade",
    "Ade", "Chiamaka", "Yetunde", "Obi", "Nkechi", "Olu",
]

def classify_age_group(age: int) -> str:
    if age <= 12:
        return "child"
    if age <= 19:
        return "teenager"
    if age <= 59:
        return "adult"
    return "senior"


def generate_row(i: int) -> dict:
    """Build one row. The row index `i` is suffixed onto the name to
    guarantee uniqueness without an O(n²) collision check."""
    country_id, country_name = random.choice(COUNTRIES)
    age = max(0, min(90, int(random.gauss(35, 18))))
    gender = random.choice(["male", "female"])
    return {
        "name": f"{random.choice(FIRST_NAMES)} Test{i:07d}",
        "gender": gender,
        "gender_probability": round(random.uniform(0.7, 0.99), 2),
        "age": age,
        "age_group": classify_age_group(age),
        "country_id": country_id,
        "country_name": country_name,
        "country_probability": round(random.uniform(0.5, 0.95), 2),
    }


def main(rows: int, output_path: str) -> None:
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    with out.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        for i in range(rows):
            writer.writerow(generate_row(i))
            if (i + 1) % 50_000 == 0:
                print(f"  generated {i + 1:,}/{rows:,}")

    size_mb = out.stat().st_size / (1024 * 1024)
    print(f"Wrote {rows:,} rows to {out} ({size_mb:.1f} MB)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows", type=int, default=100_000)
    parser.add_argument("--output", default="sample_data/profiles.csv")
    args = parser.parse_args()
    main(args.rows, args.output)