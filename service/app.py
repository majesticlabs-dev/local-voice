import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .core.config import config
from .core.dependencies import runtime_dependencies
from .providers.base import TTSProvider
from .providers.kokoro import KokoroProvider
from .api import export, health, preprocess, stop, stream, synthesize, voices

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("local_voice")

app = FastAPI(title="Local Voice TTS", version="1.0.3")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# Provider registry
_provider: TTSProvider | None = None


def get_provider() -> TTSProvider:
    global _provider
    if _provider is None:
        if config.engine == "kokoro":
            _provider = KokoroProvider()
        else:
            raise RuntimeError(f"Unknown engine: {config.engine}")
        logger.info("Loaded provider: %s", _provider.name)
    return _provider


# Routes
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
    provider_name = config.engine
    model_name = ""
    provider_ready = False
    provider_error = None

    try:
        provider = get_provider()
        provider_name = provider.name
        model_name = provider.model_name
        provider_ready = provider.is_ready()
        if provider_ready:
            logger.info("Provider %s ready", provider.name)
        else:
            logger.warning("Provider %s not ready — will retry on first request", provider.name)
    except (Exception, SystemExit) as exc:
        # SystemExit (e.g. a dependency calling sys.exit during model
        # resolution) is a BaseException, not an Exception, so it would
        # otherwise escape this guard and abort FastAPI startup.
        provider_error = exc
        logger.warning("Provider init deferred: %s", exc)

    for dependency in runtime_dependencies(
        provider_name=provider_name,
        model_name=model_name,
        provider_ready=provider_ready,
        provider_error=provider_error,
    ):
        log = logger.info if dependency["available"] else logger.warning
        log("Dependency check [%s]: %s", dependency["name"], dependency["detail"])


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=config.host, port=config.port)
