"""
Rotas para consumir a Inteligência Artificial Local (Ollama).
"""
import logging
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from pydantic import BaseModel
from typing import Dict, Any
from app.core.database import get_db
from app.models.entities import Contribuinte
from app.schemas.advisor import AdvisorRequest
from app.services.ai_advisor import get_estrategias_fiscais, gerar_defesa_malha_fina

logger = logging.getLogger(__name__)

class SolicitacaoContencioso(BaseModel):
    contribuinte_id: int
    ano: int
    malha_fina_json: Dict[str, Any]
    modelo: str | None = "deepseek-r1:14b"

router = APIRouter()

@router.post(
    "/estrategias-fiscais",
    response_model=str,
    status_code=status.HTTP_200_OK,
    tags=["IA Conselheiro"],
    summary="Analisa o JSON apurado e devolve Markdown gerado via Ollama",
    description=(
        "Esta rota é pesada e conectada ao backend nativo do Ollama (11434). "
        "Seu client deve prever latências de 1 a 15 minutos baseadas "
        "no peso (parâmetros) do modelo carregado, vram/ram disponíveis, etc."
    )
)
async def post_estrategias_fiscais(
    payload: AdvisorRequest,
    db: Session = Depends(get_db)
):
    contrib = db.get(Contribuinte, payload.contribuinte_id)
    if not contrib:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Contribuinte não encontrado."
        )

    try:
        resultado_md = await get_estrategias_fiscais(
            db=db,
            contribuinte_id=payload.contribuinte_id,
            ano_calendario=payload.ano_calendario,
            relatorio_apurado=payload.relatorio_apurado,
            dados_manuais=payload.dados_manuais,
            modelo_ollama=payload.modelo_ollama
        )
        return resultado_md
    except Exception as e:
        logger.exception("Falha completa no módulo de IA")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro subjacente consumindo IA: {str(e)}"
        )

@router.post(
    "/estrategias-fiscais/contencioso",
    response_model=str,
    status_code=status.HTTP_200_OK,
    tags=["IA Conselheiro"],
    summary="Analisa Discrepâncias de Malha Fina via IA Local",
    description="Submete o relatório do Auditor contra o e-CAC no DeepSeek."
)
async def gerar_parecer_malha_fina(
    payload: SolicitacaoContencioso,
    db: Session = Depends(get_db)
):
    try:
        resultado = await gerar_defesa_malha_fina(
            db=db,
            contribuinte_id=payload.contribuinte_id,
            ano_calendario=payload.ano,
            relatorio_auditoria=payload.malha_fina_json,
            modelo_ollama=payload.modelo or "deepseek-r1:14b"
        )
        return resultado
    except Exception as e:
        logger.exception("Invocação do Auditor IA falhou.")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro submetendo malha fina à IA: {e}"
        )
