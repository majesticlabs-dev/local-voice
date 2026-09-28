from fastapi import APIRouter

from ..core.models import VoicesResponse
from ..core.model_catalog import catalog

router = APIRouter()


def _get_provider():
    from ..app import get_provider
    return get_provider()


@router.get("/voices", response_model=VoicesResponse)
async def voices():
    provider = _get_provider()
    installed = {
        voice["id"]: voice["installed"]
        for language in catalog()["languages"]
        for voice in language["voices"]
    }
    return VoicesResponse(voices=[
        {**voice, "available": installed.get(voice["id"], False)}
        for voice in provider.list_voices()
    ])
