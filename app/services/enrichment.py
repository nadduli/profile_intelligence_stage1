import asyncio
import httpx
from fastapi import HTTPException, status
import logging

logger = logging.getLogger(__name__)


async def fetch_enrichment_data(name: str) -> tuple[dict, dict, dict]:
    """Fetch enrichment data from three external APIs with proper error handling."""
    api_names = ["Genderize", "Agify", "Nationalize"]
    urls = [
        f"https://api.genderize.io?name={name}",
        f"https://api.agify.io?name={name}",
        f"https://api.nationalize.io?name={name}",
    ]
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            responses = await asyncio.gather(
                client.get(urls[0]),
                client.get(urls[1]),
                client.get(urls[2]),
                return_exceptions=False
            )
        
        # Validate all responses have 200 status
        for i, response in enumerate(responses):
            if response.status_code != 200:
                logger.error(f"{api_names[i]} returned status {response.status_code}")
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"{api_names[i]} returned an invalid response"
                )
        
        # Parse JSON responses
        try:
            return tuple(r.json() for r in responses)
        except httpx.ResponseDecodingError as e:
            logger.error(f"Failed to decode JSON from enrichment APIs: {e}")
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Enrichment APIs returned invalid data"
            )
            
    except httpx.TimeoutException:
        logger.error(f"Timeout while calling enrichment APIs for name: {name}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to reach enrichment APIs"
        )
    except httpx.HTTPError as e:
        logger.error(f"HTTP error while calling enrichment APIs: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to reach enrichment APIs"
        )
    except Exception as e:
        logger.exception(f"Unexpected error during enrichment: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to reach enrichment APIs"
        )


def classify_age_group(age: int) -> str:
    """Classify age into groups."""
    if age <= 12:
        return "child"
    elif 13 <= age <= 19:
        return "teenager"
    elif 20 <= age <= 59:
        return "adult"
    else:
        return "senior"


async def parse_enrichment_data(genderize: dict, agify: dict, nationalize: dict) -> dict:
    """Parses and validates enrichment data, classifies age group, and returns structured response."""
    # Validate Genderize response
    if genderize.get("gender") is None or genderize.get("count") == 0:
        logger.error(f"Genderize returned invalid response: {genderize}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Genderize returned an invalid response"
        )

    # Validate Agify response
    if agify.get("age") is None:
        logger.error(f"Agify returned invalid response: {agify}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Agify returned an invalid response"
        )

    # Validate Nationalize response
    if not nationalize.get("country"):
        logger.error(f"Nationalize returned invalid response: {nationalize}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Nationalize returned an invalid response"
        )

    # Extract country with highest probability
    countries = nationalize["country"]
    top_country = max(countries, key=lambda c: c["probability"])

    age = agify["age"]
    age_group = classify_age_group(age)

    return {
        "gender": genderize["gender"],
        "gender_probability": genderize["probability"],
        "sample_size": genderize["count"],
        "age": age,
        "age_group": age_group,
        "country_id": top_country["country_id"],
        "country_probability": top_country["probability"]
    }


async def enrich_name(name: str) -> dict:
    """Main enrichment function."""
    genderize, agify, nationalize = await fetch_enrichment_data(name)
    return await parse_enrichment_data(genderize, agify, nationalize)
