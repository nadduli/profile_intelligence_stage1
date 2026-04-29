"""Stage 3 paginated response envelope: total_pages and links."""


async def test_list_includes_total_pages_and_links(client_with_data):
    response = await client_with_data.get("/api/profiles?page=1&limit=2")
    data = response.json()
    assert "total_pages" in data
    assert "links" in data
    assert "self" in data["links"]
    assert "next" in data["links"]
    assert "prev" in data["links"]


async def test_total_pages_math(client_with_data):
    response = await client_with_data.get("/api/profiles?page=1&limit=2")
    data = response.json()
    # 5 seeded profiles, limit 2 -> ceil(5/2) = 3
    assert data["total_pages"] == 3


async def test_first_page_has_no_prev(client_with_data):
    response = await client_with_data.get("/api/profiles?page=1&limit=2")
    data = response.json()
    assert data["links"]["prev"] is None
    assert data["links"]["next"] is not None


async def test_last_page_has_no_next(client_with_data):
    response = await client_with_data.get("/api/profiles?page=3&limit=2")
    data = response.json()
    assert data["links"]["next"] is None
    assert data["links"]["prev"] is not None


async def test_links_preserve_filter_params(client_with_data):
    response = await client_with_data.get(
        "/api/profiles?gender=male&page=1&limit=2"
    )
    data = response.json()
    assert "gender=male" in data["links"]["self"]
    assert "gender=male" in data["links"]["next"]


async def test_search_uses_same_envelope(client_with_data):
    response = await client_with_data.get(
        "/api/profiles/search?q=males&page=1&limit=2"
    )
    data = response.json()
    assert "total_pages" in data
    assert "links" in data
    assert data["links"]["self"].startswith("/api/profiles/search")
    assert "q=males" in data["links"]["self"]
