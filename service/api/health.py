import platform

from fastapi import APIRouter

from ..core.config import config
from ..core.dependencies import runtime_dependencies
from ..core.models import HealthResponse

router = APIRouter()


def _get_provider_statuses():
    from ..app import get_provider_statuses
    return get_provider_statuses()


@router.get("/health", response_model=HealthResponse)
async def health():
    statuses = _get_provider_statuses()
    installed = [status for status in statuses if status.installed]
    ready = bool(installed) and all(status.ready for status in installed)
    engine_label = "+".join(status.name for status in statuses) or config.engine
    model_label = "+".join(
        status.model_name for status in statuses if status.model_name
    )

    setup_needed = not installed and bool(statuses) and all(status.error is None for status in statuses)
    return HealthResponse(
        status="ok" if ready else ("setup_needed" if setup_needed else "degraded"),
        engine=engine_label,
        model=model_label,
        ready=ready,
        platform=f"{platform.system()}-{platform.machine()}",
        dependencies=runtime_dependencies(provider_statuses=statuses),
    )
