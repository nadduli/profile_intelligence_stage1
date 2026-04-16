import asyncio
import httpx
from fastapi import HTTPException, status


async def fetch_enrichment_data(name: str) -> tuple:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            results = await asyncio.gather(
                client.get(f"https://api.genderize.io?name={name}"),
                client.get(f"https://api.agify.io?name={name}"),
                client.get(f"https://api.nationalize.io?name={name}"),
                return_exceptions=False
            )
        
        for i, r in enumerate(results):
            if r.status_code != 200:
                api_names = ["Genderize", "Agify", "Nationalize"]
                raise HTTPException(
                    status_code=502,
                    detail=f"{api_names[i]} returned status {r.status_code}"
                )
        
        return tuple(r.json() for r in results)
    except (httpx.HTTPError, httpx.ResponseDecodingError) as e:
        raise HTTPException(status_code=502, detail="Enrichment API failed")

def classify_age_group(age: int) -> str:
    if age <= 12:
        return "child"
    elif 13 <= age <= 19:
        return "teenager"
    elif 20 <= age <= 59:
        return "adult"
    else:
        return "senior"


async def parse_enrichment_data(genderize: dict, agify: dict, nationalize: dict) -> dict:
    """Parses and validates the enrichment data, classifies age group, and returns a structured response."""
    if genderize.get("gender") is None or genderize.get("count") == 0:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Genderize returned an invalid response"
        )

    if agify.get("age") is None:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Agify returned an invalid response"
        )

    if not nationalize.get("country"):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Nationalize returned an invalid response"
        )

    countries = nationalize["country"]
    top_country = max(countries, key=lambda c: c["probability"])

    age = agify["age"]
    age_group = classify_age_group(age)

    return {
        "gender": genderize["gender"],
        "gender_probability": genderize["probability"],
        "sample_size": genderize["count"],
        "age": agify["age"],
        "age_group": age_group,
        "country_id": top_country["country_id"],
        "country_probability": top_country["probability"]
    }


async def enrich_name(name: str) -> dict:
    genderize, agify, nationalize = await fetch_enrichment_data(name)
    return await parse_enrichment_data(genderize, agify, nationalize)