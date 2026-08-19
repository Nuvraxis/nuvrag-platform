from pydantic import BaseModel, Field


class PageParams(BaseModel):
    limit: int = Field(default=50, ge=1, le=200)
    offset: int = Field(default=0, ge=0)


class Page[ItemT](BaseModel):
    items: list[ItemT]
    total: int
    limit: int
    offset: int


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: dict = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    error: ErrorDetail


class ComponentHealth(BaseModel):
    database: bool
    redis: bool


class HealthResponse(BaseModel):
    status: str
    environment: str
    components: ComponentHealth
