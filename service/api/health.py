import platform

from fastapi import APIRouter

from ..core.config import config
from ..core.models import HealthResponse

router = APIRouter()


def _get_provider():
    from ..app import get_provider
    return get_provider()


@router.get("/health", response_model=HealthResponse)
async def health():
    provider = _get_provider()
    return HealthResponse(
        status="ok",
        engine=provider.name,
        model=provider.model_name,
        ready=provider.is_ready(),
        platform=f"{platform.system()}-{platform.machine()}",
    )
