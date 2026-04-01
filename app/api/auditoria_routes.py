"""
Rotas para o Módulo de Auditoria Anti-Malha Fina.
Cruzamento da base e-CAC com a base local.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
import logging

from app.core.database import get_db
from app.schemas.receita import ReceitaPrePreenchidaUpload
from app.schemas.auditoria import RelatorioAuditoria
from app.services.auditor import cruzar_malha_fina

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post(
    "/auditoria/cruzar",
    response_model=RelatorioAuditoria,
    status_code=status.HTTP_200_OK,
    tags=["Auditoria"],
    summary="Inicia a varredura Anti-Malha Fina",
    description="Cruza o arquivo Pre-Preenchida do Gov.br com o banco Determinístico Local."
)
def cruzar_auditoria(
    payload: ReceitaPrePreenchidaUpload,
    contribuinte_id: int = Query(..., description="ID do contribuinte atual"),
    db: Session = Depends(get_db)
):
    try:
        return cruzar_malha_fina(contribuinte_id, payload, db)
    except Exception as e:
        logger.exception("Falha estrutural no motor de cruzamento fiscal")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro crítico na verificação contra a base do Governo: {str(e)}"
        )
