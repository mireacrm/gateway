from fastapi import Request

from app.infra.lifespan import AppContext


def get_context(request: Request) -> AppContext:
    return request.app.state.context
