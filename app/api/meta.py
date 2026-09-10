from fastapi import APIRouter, Depends

from app.api.deps import get_context
from app.api.schemas import RouteOut
from app.infra.lifespan import AppContext

router = APIRouter(tags=["meta"])


@router.get("/routes", response_model=list[RouteOut])
async def list_routes(context: AppContext = Depends(get_context)):
    """Публичная поверхность системы с требуемыми ролями."""
    return [
        RouteOut(
            method=item.method,
            path=item.path,
            upstream=item.upstream,
            roles=sorted(item.roles),
            summary=item.summary,
        )
        for item in context.router.routes()
    ]
