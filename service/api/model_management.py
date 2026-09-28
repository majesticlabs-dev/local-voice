"""Local management contract. Lifecycle operations are reserved for T03b/T03c."""
import hmac
import ipaddress
import os
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ..core.model_catalog import catalog
from ..core import model_downloads

router = APIRouter(prefix="/models", tags=["model management"])
_NATIVE_ORIGINS = {"tauri://localhost", "http://tauri.localhost", "https://tauri.localhost"}


def authorize(request: Request) -> None:
    token = os.environ.get("LV_MANAGEMENT_TOKEN", "")
    supplied = request.headers.get("X-Local-Voice-Management", "")
    origin = request.headers.get("origin")
    try:
        client = ipaddress.ip_address(request.client.host)
        host = request.url.hostname
    except (ValueError, AttributeError):
        raise HTTPException(403, "Management requires a loopback connection")
    if (not client.is_loopback or host not in {"localhost", "127.0.0.1", "[::1]", "::1"}
            or origin is not None and origin not in _NATIVE_ORIGINS):
        raise HTTPException(403, "Management requires a local native client")
    if not token or not supplied or not hmac.compare_digest(token, supplied):
        raise HTTPException(403, "Management authorization required")


LanguageId = Literal["en", "es", "ru"]


class DownloadRequest(BaseModel):
    languages: list[LanguageId] = Field(min_length=1)


class RemoveRequest(BaseModel):
    languages: list[LanguageId] = Field(min_length=1)


@router.get("", dependencies=[Depends(authorize)])
def list_models():
    return catalog()


@router.post("/downloads", status_code=202, dependencies=[Depends(authorize)])
def start_download(request: DownloadRequest):
    try:
        job, _ = model_downloads.start(request.languages)
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(409, str(exc)) from exc
    return job.response()


@router.get("/downloads/{job_id}", dependencies=[Depends(authorize)])
def download_status(job_id: str):
    job = model_downloads.get(job_id)
    if job is None:
        raise HTTPException(404, "Unknown download job")
    return job.response()


@router.post("/downloads/{job_id}/cancel", dependencies=[Depends(authorize)])
def cancel_download(job_id: str):
    job = model_downloads.cancel(job_id)
    if job is None:
        raise HTTPException(404, "Unknown download job")
    return job.response()


@router.post("/removals", status_code=501, dependencies=[Depends(authorize)])
def remove_models(request: RemoveRequest):
    raise HTTPException(501, "Removal is not implemented (T03c)")
