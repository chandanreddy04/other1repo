"""
Common dependencies for API endpoints.
Simple, straightforward utilities without over-abstraction.
"""

from fastapi import Query


def get_pagination(
    skip: int = Query(0, ge=0, description="Number of items to skip"),
    limit: int = Query(20, ge=1, le=100, description="Number of items to return"),
) -> dict:
    """
    Simple pagination parameters.

    Returns:
        dict with skip and limit values
    """
    return {"skip": skip, "limit": limit}


def get_search_params(
    q: str | None = Query(None, description="Search query"),
    skip: int = Query(0, ge=0, description="Number of items to skip"),
    limit: int = Query(20, ge=1, le=100, description="Number of items to return"),
) -> dict:
    """
    Search parameters with pagination.

    Returns:
        dict with query, skip and limit values
    """
    return {"query": q, "skip": skip, "limit": limit}
