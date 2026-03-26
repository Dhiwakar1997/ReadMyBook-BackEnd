"""API endpoints for the Neo4j social graph."""

from fastapi import APIRouter, Depends, Request, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import text

from middleware import verify_access_token
from core.db_client import get_db
from graph.data.schema import (
    RecommendationUser,
    RecommendationsResponse,
    MutualFollowerUser,
    MutualFollowersResponse,
    ShortestPathResponse,
    InfluenceResponse,
    GraphHealthResponse,
)
from graph.service.recommendation_service import RecommendationService

graph_router = APIRouter(prefix="/graph", tags=["graph"])

_recommendation_service = RecommendationService()


@graph_router.get(
    "/recommendations",
    response_model=RecommendationsResponse,
    dependencies=[Depends(verify_access_token)],
)
def get_recommendations(request: Request, limit: int = Query(20, ge=1, le=50)):
    user_id = request.state.user_id
    results = _recommendation_service.get_people_you_may_know(user_id, limit)
    users = [
        RecommendationUser(
            user_id=r["user_id"],
            first_name=r.get("first_name", ""),
            last_name=r.get("last_name"),
            mutual_count=r.get("mutual_count", 0),
            follower_count=r.get("follower_count", 0),
        )
        for r in results
    ]
    return RecommendationsResponse(users=users)


@graph_router.get(
    "/mutual-followers/{user_id}",
    response_model=MutualFollowersResponse,
    dependencies=[Depends(verify_access_token)],
)
def get_mutual_followers(
    user_id: str,
    request: Request,
    db: Session = Depends(get_db),
    limit: int = Query(50, ge=1, le=100),
):
    current_user_id = request.state.user_id
    results = _recommendation_service.get_mutual_followers(current_user_id, user_id, limit)

    # PG fallback if Neo4j unavailable
    if results is None:
        sql = text("""
            SELECT u.user_id, u.first_name, u.last_name
            FROM follows f1
            JOIN follows f2 ON f1.follower_id = f2.follower_id
            JOIN users u ON u.user_id = f1.follower_id
            WHERE f1.following_id = :user_a
              AND f2.following_id = :user_b
              AND f1.follower_id != :user_a
              AND f1.follower_id != :user_b
            LIMIT :limit
        """)
        rows = db.execute(
            sql, {"user_a": current_user_id, "user_b": user_id, "limit": limit}
        ).fetchall()
        results = [
            {"user_id": r[0], "first_name": r[1], "last_name": r[2]} for r in rows
        ]

    users = [
        MutualFollowerUser(
            user_id=r["user_id"],
            first_name=r.get("first_name", ""),
            last_name=r.get("last_name"),
        )
        for r in results
    ]
    return MutualFollowersResponse(users=users)


@graph_router.get(
    "/shortest-path/{target_user_id}",
    response_model=ShortestPathResponse,
    dependencies=[Depends(verify_access_token)],
)
def get_shortest_path(target_user_id: str, request: Request):
    current_user_id = request.state.user_id
    result = _recommendation_service.get_shortest_path(current_user_id, target_user_id)
    if result is None:
        raise HTTPException(status_code=503, detail="Graph database unavailable")
    return ShortestPathResponse(path=result["user_ids"], distance=result["distance"])


@graph_router.get(
    "/influence/{user_id}",
    response_model=InfluenceResponse,
    dependencies=[Depends(verify_access_token)],
)
def get_influence(user_id: str):
    result = _recommendation_service.get_influence_score(user_id)
    if result is None:
        raise HTTPException(status_code=503, detail="Graph database unavailable")
    return InfluenceResponse(
        user_id=user_id,
        direct_followers=result.get("direct_followers", 0),
        second_degree_reach=result.get("second_degree_reach", 0),
    )


@graph_router.get(
    "/health",
    response_model=GraphHealthResponse,
    dependencies=[Depends(verify_access_token)],
)
def graph_health():
    result = _recommendation_service.health_check()
    if result is None:
        return GraphHealthResponse(status="unavailable")
    return GraphHealthResponse(
        status="ok",
        node_count=result.get("node_count", 0),
        edge_count=result.get("edge_count", 0),
    )
