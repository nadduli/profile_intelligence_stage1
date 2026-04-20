import uuid


async def test_create_profile_empty_name(client):
    """Empty name should return 422."""
    response = await client.post("/api/profiles", json={"name": ""})
    assert response.status_code == 422
    assert response.json()["status"] == "error"


async def test_create_profile_missing_name(client):
    """Missing name field should return 422."""
    response = await client.post("/api/profiles", json={})
    assert response.status_code == 422
    assert response.json()["status"] == "error"


async def test_get_profile_not_found(client):
    """Non-existent UUID should return 404."""
    fake_id = str(uuid.uuid4())
    response = await client.get(f"/api/profiles/{fake_id}")
    assert response.status_code == 404
    assert response.json()["status"] == "error"
    assert response.json()["message"] == "Profile not found"


async def test_delete_profile_not_found(client):
    """Deleting non-existent profile should return 404."""
    fake_id = str(uuid.uuid4())
    response = await client.delete(f"/api/profiles/{fake_id}")
    assert response.status_code == 404
    assert response.json()["status"] == "error"


# ---------------------------------------------------------------------------
# GET /api/profiles — pagination envelope
# ---------------------------------------------------------------------------


async def test_list_profiles_returns_paginated_envelope(client_with_data):
    """Response must include status, page, limit, total, data."""
    response = await client_with_data.get("/api/profiles")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert "page" in data
    assert "limit" in data
    assert "total" in data
    assert isinstance(data["data"], list)


async def test_list_profiles_total_count(client_with_data):
    """Total should reflect full count of seeded profiles."""
    response = await client_with_data.get("/api/profiles")
    assert response.json()["total"] == 5


async def test_list_profiles_pagination_limit(client_with_data):
    """Limit param should cap the number of results returned."""
    response = await client_with_data.get("/api/profiles?page=1&limit=2")
    data = response.json()
    assert data["page"] == 1
    assert data["limit"] == 2
    assert len(data["data"]) == 2
    assert data["total"] == 5


async def test_list_profiles_pagination_page2(client_with_data):
    """Page 2 with limit 2 should return next batch."""
    response = await client_with_data.get("/api/profiles?page=2&limit=2")
    data = response.json()
    assert data["page"] == 2
    assert len(data["data"]) == 2


# ---------------------------------------------------------------------------
# GET /api/profiles — filtering
# ---------------------------------------------------------------------------


async def test_filter_by_gender_female(client_with_data):
    """Filter by gender=female should return only females."""
    response = await client_with_data.get("/api/profiles?gender=female")
    data = response.json()
    assert data["status"] == "success"
    assert data["total"] == 2  # Alice + Fatima
    assert all(p["gender"] == "female" for p in data["data"])


async def test_filter_by_gender_male(client_with_data):
    """Filter by gender=male should return only males."""
    response = await client_with_data.get("/api/profiles?gender=male")
    data = response.json()
    assert data["total"] == 3  # Kwame + Emeka + Amara
    assert all(p["gender"] == "male" for p in data["data"])


async def test_filter_by_country_id(client_with_data):
    """Filter by country_id=NG should return only Nigerian profiles."""
    response = await client_with_data.get("/api/profiles?country_id=NG")
    data = response.json()
    assert data["total"] == 2  # Alice + Emeka
    assert all(p["country_id"] == "NG" for p in data["data"])


async def test_filter_by_age_group(client_with_data):
    """Filter by age_group=adult should return only adults."""
    response = await client_with_data.get("/api/profiles?age_group=adult")
    data = response.json()
    assert data["total"] == 2
    assert all(p["age_group"] == "adult" for p in data["data"])


async def test_filter_by_min_age(client_with_data):
    """min_age=30 should return profiles aged 30 and above."""
    response = await client_with_data.get("/api/profiles?min_age=30")
    data = response.json()
    assert all(p["age"] >= 30 for p in data["data"])
    assert data["total"] == 2


async def test_filter_by_max_age(client_with_data):
    """max_age=20 should return profiles aged 20 and below."""
    response = await client_with_data.get("/api/profiles?max_age=20")
    data = response.json()
    assert all(p["age"] <= 20 for p in data["data"])
    assert data["total"] == 2


async def test_combined_filters(client_with_data):
    """Combined gender + country_id must both apply (AND logic)."""
    response = await client_with_data.get("/api/profiles?gender=male&country_id=NG")
    data = response.json()
    assert data["total"] == 1
    assert data["data"][0]["name"] == "Emeka Eze"


async def test_combined_gender_age_filters(client_with_data):
    """Combined gender + min_age filter."""
    response = await client_with_data.get("/api/profiles?gender=female&min_age=30")
    data = response.json()
    assert data["total"] == 1
    assert data["data"][0]["name"] == "Fatima Diallo"


# ---------------------------------------------------------------------------
# GET /api/profiles — sorting
# ---------------------------------------------------------------------------


async def test_sort_by_age_asc(client_with_data):
    """sort_by=age&order=asc should return youngest first."""
    response = await client_with_data.get("/api/profiles?sort_by=age&order=asc&limit=5")
    ages = [p["age"] for p in response.json()["data"]]
    assert ages == sorted(ages)


async def test_sort_by_age_desc(client_with_data):
    """sort_by=age&order=desc should return oldest first."""
    response = await client_with_data.get(
        "/api/profiles?sort_by=age&order=desc&limit=5"
    )
    ages = [p["age"] for p in response.json()["data"]]
    assert ages == sorted(ages, reverse=True)


async def test_sort_by_gender_probability(client_with_data):
    """sort_by=gender_probability should be a valid sort field."""
    response = await client_with_data.get(
        "/api/profiles?sort_by=gender_probability&order=desc&limit=5"
    )
    assert response.status_code == 200
    probs = [p["gender_probability"] for p in response.json()["data"]]
    assert probs == sorted(probs, reverse=True)


# ---------------------------------------------------------------------------
# GET /api/profiles — validation
# ---------------------------------------------------------------------------


async def test_invalid_sort_by(client_with_data):
    """Invalid sort_by value should return 400."""
    response = await client_with_data.get("/api/profiles?sort_by=name")
    assert response.status_code == 400
    assert response.json()["status"] == "error"
    assert response.json()["message"] == "Invalid query parameters"


async def test_invalid_order(client_with_data):
    """Invalid order value should return 400."""
    response = await client_with_data.get("/api/profiles?order=random")
    assert response.status_code == 400
    assert response.json()["status"] == "error"


async def test_limit_exceeds_max(client_with_data):
    """limit > 50 should return 400."""
    response = await client_with_data.get("/api/profiles?limit=100")
    assert response.status_code == 400
    assert response.json()["status"] == "error"


async def test_invalid_page(client_with_data):
    """page < 1 should return 400."""
    response = await client_with_data.get("/api/profiles?page=0")
    assert response.status_code == 400
    assert response.json()["status"] == "error"


# ---------------------------------------------------------------------------
# GET /api/profiles/search — natural language query
# ---------------------------------------------------------------------------


async def test_search_by_gender_female(client_with_data):
    """Query 'females' should return only female profiles."""
    response = await client_with_data.get("/api/profiles/search?q=females")
    data = response.json()
    assert data["status"] == "success"
    assert data["total"] == 2
    assert all(p["gender"] == "female" for p in data["data"])


async def test_search_by_gender_male(client_with_data):
    """Query 'males' should return only male profiles."""
    response = await client_with_data.get("/api/profiles/search?q=males")
    data = response.json()
    assert data["status"] == "success"
    assert data["total"] == 3
    assert all(p["gender"] == "male" for p in data["data"])


async def test_search_by_country(client_with_data):
    """Query 'people from nigeria' should return only NG profiles."""
    response = await client_with_data.get("/api/profiles/search?q=people+from+nigeria")
    data = response.json()
    assert data["status"] == "success"
    assert data["total"] == 2
    assert all(p["country_id"] == "NG" for p in data["data"])


async def test_search_young_males(client_with_data):
    """'young males' maps to gender=male + min_age=16 + max_age=24."""
    response = await client_with_data.get("/api/profiles/search?q=young+males")
    data = response.json()
    assert data["status"] == "success"
    assert data["total"] == 1  # only Kwame (17)
    for p in data["data"]:
        assert p["gender"] == "male"
        assert 16 <= p["age"] <= 24


async def test_search_females_above_30(client_with_data):
    """'females above 30' maps to gender=female + min_age=30."""
    response = await client_with_data.get("/api/profiles/search?q=females+above+30")
    data = response.json()
    assert data["status"] == "success"
    assert data["total"] == 1  # only Fatima (65)
    assert data["data"][0]["name"] == "Fatima Diallo"


async def test_search_combined(client_with_data):
    """'adult males from nigeria' should combine all three filters."""
    response = await client_with_data.get(
        "/api/profiles/search?q=adult+males+from+nigeria"
    )
    data = response.json()
    assert data["status"] == "success"
    assert data["total"] == 1
    assert data["data"][0]["name"] == "Emeka Eze"


async def test_search_age_group_senior(client_with_data):
    """'senior females' should return senior female profiles."""
    response = await client_with_data.get("/api/profiles/search?q=senior+females")
    data = response.json()
    assert data["status"] == "success"
    assert data["total"] == 1  # only Fatima
    assert data["data"][0]["age_group"] == "senior"


async def test_search_uninterpretable_query(client_with_data):
    """Gibberish query should return unable to interpret error."""
    response = await client_with_data.get("/api/profiles/search?q=xyzzy+foobar+blah")
    data = response.json()
    assert data["status"] == "error"
    assert data["message"] == "Unable to interpret query"


async def test_search_missing_q(client_with_data):
    """Missing q param should return 422."""
    response = await client_with_data.get("/api/profiles/search")
    assert response.status_code == 422


async def test_search_pagination(client_with_data):
    """Search results should respect page and limit params."""
    response = await client_with_data.get("/api/profiles/search?q=males&page=1&limit=2")
    data = response.json()
    assert data["status"] == "success"
    assert data["page"] == 1
    assert data["limit"] == 2
    assert len(data["data"]) <= 2
    assert data["total"] == 3


# ---------------------------------------------------------------------------
# GET /api/profiles/stats
# ---------------------------------------------------------------------------


async def test_stats_structure(client_with_data):
    """Stats response must include total, by_gender, by_age_group, top_countries."""
    response = await client_with_data.get("/api/profiles/stats")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert "total" in data["data"]
    assert "by_gender" in data["data"]
    assert "by_age_group" in data["data"]
    assert "top_countries" in data["data"]


async def test_stats_total(client_with_data):
    """Stats total should equal the number of seeded profiles."""
    response = await client_with_data.get("/api/profiles/stats")
    assert response.json()["data"]["total"] == 5


async def test_stats_gender_counts(client_with_data):
    """Stats gender breakdown should match seeded data."""
    data = (await client_with_data.get("/api/profiles/stats")).json()["data"]
    assert data["by_gender"]["female"] == 2
    assert data["by_gender"]["male"] == 3


async def test_stats_top_countries(client_with_data):
    """Top countries list should be ordered by count descending."""
    data = (await client_with_data.get("/api/profiles/stats")).json()["data"]
    counts = [c["count"] for c in data["top_countries"]]
    assert counts == sorted(counts, reverse=True)
    # Nigeria has 2 profiles — should be first
    assert data["top_countries"][0]["country_id"] == "NG"
    assert data["top_countries"][0]["count"] == 2


async def test_stats_age_group_keys(client_with_data):
    """Age group breakdown should contain all groups present in seeded data."""
    data = (await client_with_data.get("/api/profiles/stats")).json()["data"]
    age_groups = data["by_age_group"]
    assert "adult" in age_groups
    assert "teenager" in age_groups
    assert "senior" in age_groups
    assert "child" in age_groups
