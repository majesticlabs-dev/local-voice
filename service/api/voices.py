from fastapi import APIRouter

from ..core.models import VoicesResponse

router = APIRouter()


def _get_provider():
    from ..app import get_provider
    return get_provider()


@router.get("/voices", response_model=VoicesResponse)
async def voices():
    provider = _get_provider()
    return VoicesResponse(voices=provider.list_voices())
