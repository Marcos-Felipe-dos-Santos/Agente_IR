"""
Ponto de entrada da aplicação FastAPI.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.api.upload_routes import router as upload_router
from app.api.apuracao_routes import router as apuracao_router
from app.core.config import APP_TITLE, APP_VERSION
from app.core.database import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Cria as tabelas no startup."""
    init_db()
    yield


app = FastAPI(
    title=APP_TITLE,
    version=APP_VERSION,
    lifespan=lifespan,
)

# Configurar CORS (Liberando o Front-End local)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",  # Padrão Vite
        "http://127.0.0.1:5173",
        "http://localhost:3000",  # Alternativa (se mudar porta)
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api/v1")
app.include_router(upload_router, prefix="/api/v1")
app.include_router(apuracao_router, prefix="/api/v1")


@app.get("/health", tags=["Sistema"])
def health_check():
    return {"status": "ok", "version": APP_VERSION}
