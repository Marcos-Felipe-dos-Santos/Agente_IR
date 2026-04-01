"""
Rotas para relatórios e consolidações executivas em PDF.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
import io

from app.core.database import get_db
from app.services.consolidator import gerar_dossie_pdf
import logging

logger = logging.getLogger(__name__)

router = APIRouter()

class DossieRequest(BaseModel):
    contribuinte_id: int
    ano: int
    parecer_ia: str


@router.post(
    "/relatorios/dossie",
    status_code=status.HTTP_200_OK,
    tags=["Relatórios Executivos"],
    summary="Gera Dossiê Fiscal Completo em PDF",
    description="Baixa o arquivo PDF consolidando B3, RH, Saúde e IA.",
)
def download_dossie_pdf(
    payload: DossieRequest,
    db: Session = Depends(get_db)
):
    try:
        pdf_bytes = gerar_dossie_pdf(
            contribuinte_id=payload.contribuinte_id,
            ano=payload.ano,
            parecer_ia=payload.parecer_ia,
            db=db
        )
    except Exception as e:
        logger.exception("Erro ao gerar PDF")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Falha ao compilar relatório Executivo: {str(e)}"
        )
        
    return StreamingResponse(
        iter([pdf_bytes]),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="Dossie_IRPF_{payload.ano}.pdf"'
        }
    )
