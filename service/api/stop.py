from fastapi import APIRouter

from ..core.models import StopRequest
from ..core.jobs import registry

router = APIRouter()


@router.post("/stop")
async def stop(req: StopRequest):
    cancelled = registry.cancel(req.job_id)
    return {"ok": cancelled}
