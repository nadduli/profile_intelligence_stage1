"""HTTP client for GitHub's OAuth and user-info endpoints.
"""

import httpx

GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_USER_URL = "https://api.github.com/user"


class GitHubOAuthError(Exception):
    """Raised when GitHub rejects an OAuth code or returns an unexpected response."""


async def exchange_code(
    *,
    code: str,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
    code_verifier: str | None = None,
) -> str:
    """Exchange a one-time authorization code for a GitHub access token."""
    payload = {
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "redirect_uri": redirect_uri,
    }
    if code_verifier is not None:
        payload["code_verifier"] = code_verifier

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(
            GITHUB_TOKEN_URL,
            data=payload,
            headers={"Accept": "application/json"},
        )

    if response.status_code != 200:
        raise GitHubOAuthError(
            f"GitHub token exchange returned {response.status_code}"
        )

    body = response.json()
    if "error" in body:
        raise GitHubOAuthError(
            f"GitHub: {body['error']}: {body.get('error_description', '')}"
        )

    access_token = body.get("access_token")
    if not access_token:
        raise GitHubOAuthError("GitHub token exchange returned no access_token")

    return access_token


async def fetch_user(access_token: str) -> dict:
    """Fetch the authenticated user's profile from GitHub."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(
            GITHUB_USER_URL,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/vnd.github+json",
            },
        )

    if response.status_code != 200:
        raise GitHubOAuthError(
            f"GitHub /user returned {response.status_code}"
        )

    return response.json()
