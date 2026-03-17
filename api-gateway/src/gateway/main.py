from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from gateway.routes import config, defectdojo, health, reviews

app = FastAPI(title="Code Review Gateway")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, prefix="/api")
app.include_router(config.router, prefix="/api")
app.include_router(defectdojo.router, prefix="/api")
app.include_router(reviews.router, prefix="/api")
