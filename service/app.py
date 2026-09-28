import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from .core.config import config
from .core.dependencies import ProviderStatus, runtime_dependencies
from .providers.base import TTSProvider
from .core.setup import SetupNeeded
from .core import model_lifecycle
from .providers.kokoro import KokoroProvider
from .api import export, health, model_management, preprocess, stop, stream, synthesize, voices

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("local_voice")

app = FastAPI(title="Local Voice TTS", version="1.2.0")


@app.exception_handler(SetupNeeded)
async def setup_needed(_request: Request, exc: SetupNeeded):
    return JSONResponse(status_code=503, content={
        "error": "setup_needed", "voice": exc.voice, "assets": exc.assets,
        "detail": str(exc),
    })

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# Provider registry
_provider: TTSProvider | None = None


def _release_provider_caches(assets: set[str]) -> None:
    from .providers.piper import PiperProvider
    KokoroProvider().release_assets(assets)
    PiperProvider().release_assets(assets)
    if "spacy-en-core-web-sm" in assets:
        from .core import spacy_model
        spacy_model.deactivate()


model_lifecycle.register_release(_release_provider_caches)


def get_provider() -> TTSProvider:
    global _provider
    if _provider is None:
        _provider = _build_provider()
        logger.info("Loaded provider: %s", _provider.name)
    return _provider


def get_provider_statuses() -> list[ProviderStatus]:
    """Readiness of every engine backing the service. A router fans out to
    its children so health covers all engines, not just the default one."""
    try:
        provider = get_provider()
    except (Exception, SystemExit) as exc:
        return [ProviderStatus(name=config.engine, error=exc)]

    from .providers.router import RouterProvider

    children = provider.providers if isinstance(provider, RouterProvider) else [provider]
    statuses: list[ProviderStatus] = []
    for child in children:
        status = ProviderStatus(name=child.name, model_name=child.model_name)
        try:
            from .core.setup import has_local_voice
            status.installed = has_local_voice(child.name)
            status.ready = child.is_ready()
        except (Exception, SystemExit) as exc:
            status.error = exc
        statuses.append(status)
    return statuses


def _build_provider() -> TTSProvider:
    from .providers.piper import PiperProvider

    if config.engine == "piper":
        return PiperProvider()
    if config.engine != "kokoro":
        raise RuntimeError(f"Unknown engine: {config.engine}")

    # Default engine: Kokoro for its supported languages, Piper for Russian.
    kokoro = KokoroProvider()
    providers: list[TTSProvider] = [kokoro, PiperProvider()]

    from .providers.router import RouterProvider
    return RouterProvider(providers, default=kokoro)


# Routes
app.include_router(model_management.router)
app.include_router(health.router)
app.include_router(voices.router)
app.include_router(synthesize.router)
app.include_router(stream.router)
app.include_router(stop.router)
app.include_router(preprocess.router)
app.include_router(export.router)


@app.on_event("startup")
async def startup():
    config.cache_dir.mkdir(parents=True, exist_ok=True)
    config.output_dir.mkdir(parents=True, exist_ok=True)
    logger.info("Local Voice TTS starting on %s:%d (engine=%s)", config.host, config.port, config.engine)

    statuses = get_provider_statuses()
    for status in statuses:
        if status.error is not None:
            logger.warning("Provider %s init deferred: %s", status.name, status.error)
        elif status.ready:
            logger.info("Provider %s ready (%s)", status.name, status.model_name)
        else:
            logger.warning("Provider %s not ready — will retry on first request", status.name)

    for dependency in runtime_dependencies(provider_statuses=statuses):
        log = logger.info if dependency["available"] else logger.warning
        log("Dependency check [%s]: %s", dependency["name"], dependency["detail"])


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=config.host, port=config.port)
