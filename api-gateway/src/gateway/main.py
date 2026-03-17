import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from gateway.routes import config, defectdojo, health, prompts, reviews

limiter = Limiter(key_func=get_remote_address)

app = FastAPI(title="Code Review Gateway")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

allowed_origins = os.getenv(
    "CORS_ALLOWED_ORIGINS", "http://localhost:5173,http://localhost:80"
).split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in allowed_origins],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, prefix="/api")
app.include_router(config.router, prefix="/api")
app.include_router(defectdojo.router, prefix="/api")
app.include_router(reviews.router, prefix="/api")
app.include_router(prompts.router, prefix="/api")
