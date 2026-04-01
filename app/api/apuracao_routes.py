"""
Rotas para apuração tributária anual e mensal.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.entities import Contribuinte
from app.schemas.apuracao import RelatorioAnualBase
from app.services.tax_engine import apurar_meses_b3, auditar_cripto_vendas
import logging

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get(
    "/apuracao/relatorio-anual",
    response_model=RelatorioAnualBase,
    status_code=status.HTTP_200_OK,
    tags=["Apuração / Impostos"],
    summary="Gera relatório de apuração de IR anual",
    description=(
        "Executa o motor de regras da Receita Federal (recalculando estoques "
        "cronologicamente) para determinar lucros isentos (vendas <= 20k), "
        "tributáveis, DARFs devidos e carrega prejuízos compensáveis. "
        "Também audita limites mensais de criptomoedas."
    )
)
def get_relatorio_anual(
    contribuinte_id: int = Query(..., description="ID do contribuinte"),
    ano: int = Query(..., description="Ano-calendário para consolidação"),
    db: Session = Depends(get_db)
):
    contrib = db.get(Contribuinte, contribuinte_id)
    if not contrib:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Contribuinte não encontrado."
        )

    # 1. Apuração B3 (Ações / Swing Trade)
    try:
        meses_apurados, prejuizo_final = apurar_meses_b3(contribuinte_id, ano, db)
    except Exception as e:
        logger.exception("Erro na engine matemática (B3)")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Falha ao apurar impostos B3: {e}"
        )

    # 2. Auditoria Criptoativos
    try:
        alertas_cripto = auditar_cripto_vendas(contribuinte_id, ano, db)
    except Exception as e:
        logger.exception("Erro na engine matemática (Cripto)")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Falha ao auditar limites de criptomoedas: {e}"
        )

    # 3. Consolidar Totais
    total_isento = sum((float(item["lucro_isento"]) for item in meses_apurados))
    total_tributavel = sum((float(item["lucro_tributavel"]) for item in meses_apurados))
    total_imposto = sum((float(item["imposto_devido"]) for item in meses_apurados))

    return {
        "contribuinte_id": contribuinte_id,
        "ano_calendario": ano,
        "meses": meses_apurados,
        "total_lucro_isento_ano": f"{total_isento:.2f}",
        "total_lucro_tributavel_ano": f"{total_tributavel:.2f}",
        "total_imposto_devido_ano": f"{total_imposto:.2f}",
        "saldo_prejuizo_a_compensar_final_ano": f"{prejuizo_final:.2f}",
        "alertas_cripto": alertas_cripto
    }
