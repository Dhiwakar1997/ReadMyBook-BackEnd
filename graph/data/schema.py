"""Pydantic response models for graph endpoints."""

from pydantic import BaseModel


class RecommendationUser(BaseModel):
    user_id: str
    first_name: str
    last_name: str | None = None
    mutual_count: int = 0
    follower_count: int = 0


class RecommendationsResponse(BaseModel):
    users: list[RecommendationUser]


class MutualFollowerUser(BaseModel):
    user_id: str
    first_name: str
    last_name: str | None = None


class MutualFollowersResponse(BaseModel):
    users: list[MutualFollowerUser]


class ShortestPathResponse(BaseModel):
    path: list[str]
    distance: int


class InfluenceResponse(BaseModel):
    user_id: str
    direct_followers: int = 0
    second_degree_reach: int = 0


class GraphHealthResponse(BaseModel):
    status: str
    node_count: int = 0
    edge_count: int = 0
