import platform

from fastapi import APIRouter

from ..core.config import config
from ..core.dependencies import runtime_dependencies
from ..core.models import HealthResponse

router = APIRouter()


def _get_provider():
    from ..app import get_provider
    return get_provider()


@router.get("/health", response_model=HealthResponse)
async def health():
    provider_name = config.engine
    model_name = ""
    provider_ready = False
    provider_error = None

    try:
        provider = _get_provider()
        provider_name = provider.name
        model_name = provider.model_name
        provider_ready = provider.is_ready()
    except Exception as exc:
        provider_error = exc

    return HealthResponse(
        status="ok" if provider_ready else "degraded",
        engine=provider_name,
        model=model_name,
        ready=provider_ready,
        platform=f"{platform.system()}-{platform.machine()}",
        dependencies=runtime_dependencies(
            provider_name=provider_name,
            model_name=model_name,
            provider_ready=provider_ready,
            provider_error=provider_error,
        ),
    )
