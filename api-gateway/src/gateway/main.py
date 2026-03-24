import os
import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from loguru import logger
from prometheus_fastapi_instrumentator import Instrumentator
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from starlette.middleware.base import BaseHTTPMiddleware

from gateway.routes import config, defectdojo, health, prompts, reviews, webhook
from gateway.utils.ratelimit import limiter

app = FastAPI(title="Code Review Gateway")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start = time.time()
        response = await call_next(request)
        duration = time.time() - start
        logger.info(
            "{} {} {} {:.3f}s",
            request.method,
            request.url.path,
            response.status_code,
            duration,
        )
        return response


app.add_middleware(RequestLoggingMiddleware)

allowed_origins = os.getenv(
    "CORS_ALLOWED_ORIGINS", "http://localhost:5173,http://localhost:80"
).split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in allowed_origins],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Request-ID"],
)


@app.exception_handler(Exception)
async def generic_handler(request: Request, exc: Exception):
    logger.error("Unhandled exception on {} {}: {}", request.method, request.url.path, exc)
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error"},
    )


app.include_router(health.router, prefix="/api")
app.include_router(config.router, prefix="/api")
app.include_router(defectdojo.router, prefix="/api")
app.include_router(reviews.router, prefix="/api")
app.include_router(prompts.router, prefix="/api")
app.include_router(webhook.router, prefix="/api")

Instrumentator().instrument(app).expose(app, endpoint="/metrics")
