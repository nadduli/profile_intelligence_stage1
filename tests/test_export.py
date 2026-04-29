"""CSV export endpoint."""

import csv
import io


async def test_export_returns_csv_content_type(client_with_data):
    response = await client_with_data.get("/api/profiles/export?format=csv")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")


async def test_export_filename_in_disposition(client_with_data):
    response = await client_with_data.get("/api/profiles/export?format=csv")
    cd = response.headers["content-disposition"]
    assert "attachment" in cd
    assert "filename=" in cd
    assert "profiles_" in cd
    assert ".csv" in cd


async def test_export_columns_match_spec(client_with_data):
    response = await client_with_data.get("/api/profiles/export?format=csv")
    reader = csv.reader(io.StringIO(response.text))
    header = next(reader)
    expected = [
        "id",
        "name",
        "gender",
        "gender_probability",
        "age",
        "age_group",
        "country_id",
        "country_name",
        "country_probability",
        "created_at",
    ]
    assert header == expected


async def test_export_row_count_matches_total(client_with_data):
    response = await client_with_data.get("/api/profiles/export?format=csv")
    rows = list(csv.reader(io.StringIO(response.text)))
    # 1 header + 5 seeded profiles
    assert len(rows) == 6


async def test_export_filter_applies(client_with_data):
    response = await client_with_data.get(
        "/api/profiles/export?format=csv&gender=female"
    )
    rows = list(csv.reader(io.StringIO(response.text)))
    # 1 header + 2 females (Alice, Fatima)
    assert len(rows) == 3
    for row in rows[1:]:
        assert row[2] == "female"  # gender column


async def test_export_unsupported_format_returns_400(client_with_data):
    response = await client_with_data.get("/api/profiles/export?format=json")
    assert response.status_code == 400


async def test_export_requires_auth(unauth_client):
    response = await unauth_client.get("/api/profiles/export?format=csv")
    assert response.status_code == 401
