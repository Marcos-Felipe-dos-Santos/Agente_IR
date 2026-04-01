"""
Rotas de upload — ingestão de arquivos CSV/PDF.
"""

import logging

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.upload import B3UploadResponse, InformeUploadResponse
from app.services.b3_parser import ingest_b3_csv_upload
from app.services.pdf_parser import ingest_informe_pdf

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post(
    "/upload/b3-csv",
    response_model=B3UploadResponse,
    status_code=status.HTTP_200_OK,
    tags=["Upload / Importação"],
    summary="Importa CSV de negociação/movimentação da B3",
    description=(
        "Recebe o CSV exportado da 'Área do Investidor' da B3, "
        "limpa os dados, calcula preço médio de aquisição ponderado "
        "por ticker e insere as operações na tabela OperacaoB3."
    ),
)
async def upload_b3_csv(
    file: UploadFile = File(
        ...,
        description="Arquivo CSV da B3 (negociação ou movimentação)",
    ),
    contribuinte_id: int = Query(
        ...,
        ge=1,
        description="ID do contribuinte para vincular as operações",
    ),
    encoding: str = Query(
        default="utf-8",
        description="Encoding do arquivo CSV (utf-8, latin-1, cp1252)",
    ),
    corretora: str | None = Query(
        default=None,
        description="Nome da corretora (sobrescreve valor do CSV, se informado)",
    ),
    db: Session = Depends(get_db),
):
    # Validação do tipo de arquivo
    if file.content_type and "csv" not in file.content_type and "text" not in file.content_type:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Tipo de arquivo não suportado: {file.content_type}. Envie um CSV.",
        )

    try:
        result = ingest_b3_csv_upload(
            file_content=file.file,
            contribuinte_id=contribuinte_id,
            db=db,
            encoding=encoding,
            corretora_override=corretora,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        )
    except Exception as e:
        logger.exception("Erro inesperado ao processar CSV da B3")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro interno ao processar o arquivo: {e}",
        )

    # Se houve erros críticos que impediram inserção
    if result.operacoes_inseridas == 0 and result.erros:
        return B3UploadResponse(
            status="erro",
            total_linhas_csv=result.total_linhas_csv,
            operacoes_inseridas=0,
            operacoes_ignoradas=result.operacoes_ignoradas,
            desdobramentos_detectados=result.desdobramentos_detectados,
            erros=result.erros,
            precos_medios={},
        )

    return B3UploadResponse(
        status="sucesso",
        total_linhas_csv=result.total_linhas_csv,
        operacoes_inseridas=result.operacoes_inseridas,
        operacoes_ignoradas=result.operacoes_ignoradas,
        desdobramentos_detectados=result.desdobramentos_detectados,
        erros=result.erros,
        precos_medios=result.precos_medios,
    )


# ═══════════════════════════════════════════════════════════════════
#  Upload de Informe de Rendimentos (PDF)
# ═══════════════════════════════════════════════════════════════════
@router.post(
    "/upload/informe-pdf",
    response_model=InformeUploadResponse,
    status_code=status.HTTP_200_OK,
    tags=["Upload / Importação"],
    summary="Importa Informe de Rendimentos Financeiros em PDF",
    description=(
        "Recebe o PDF do Informe de Rendimentos Financeiros emitido "
        "por bancos e corretoras. Extrai CNPJ, rendimentos (tributação "
        "exclusiva, isentos, tributáveis) e saldos em 31/12. "
        "Persiste os dados no banco de dados."
    ),
)
async def upload_informe_pdf(
    file: UploadFile = File(
        ...,
        description="Arquivo PDF do Informe de Rendimentos Financeiros",
    ),
    contribuinte_id: int = Query(
        ...,
        ge=1,
        description="ID do contribuinte para vincular os dados",
    ),
    db: Session = Depends(get_db),
):
    # Validação do tipo de arquivo
    if file.content_type and "pdf" not in file.content_type:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Tipo de arquivo não suportado: {file.content_type}. Envie um PDF.",
        )

    try:
        result = ingest_informe_pdf(
            file_content=file.file,
            contribuinte_id=contribuinte_id,
            db=db,
        )
    except Exception as e:
        logger.exception("Erro inesperado ao processar PDF do informe")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro interno ao processar o arquivo: {e}",
        )

    status_label = "sucesso" if result.rendimentos_inseridos > 0 or result.saldos_atualizados > 0 else "erro"

    return InformeUploadResponse(
        status=status_label,
        cnpj_fonte=result.cnpj_fonte,
        razao_social=result.razao_social,
        ano_calendario=result.ano_calendario,
        rendimentos_inseridos=result.rendimentos_inseridos,
        saldos_atualizados=result.saldos_atualizados,
        erros=result.erros,
        rendimentos=result.rendimentos_detalhe,
        saldos=result.saldos_detalhe,
    )
