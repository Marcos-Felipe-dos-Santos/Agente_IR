"""
Serviço de ingestão de Informes de Rendimentos Financeiros em PDF.

Este módulo é a fachada pública do sistema de parsing. Ele:
  1. Extrai texto do PDF via pdfplumber.
  2. Delega o parsing ao ParserFactory (Padrão Strategy).
  3. Persiste os dados extraídos no banco de dados.

A lógica de extração em si NÃO vive aqui — está encapsulada nas estratégias
em app/services/pdf_strategies/. Para adicionar suporte a novo banco,
não edite este arquivo: adicione uma nova estratégia e registre na Factory.
"""
from __future__ import annotations

import io
import logging
import re
from dataclasses import dataclass, field
from decimal import Decimal
from typing import BinaryIO

import pdfplumber
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import (
    ContaBancaria,
    Contribuinte,
    DespesaMedica,
    RendimentoInforme,
    RendimentoTrabalho,
)
from app.services.pdf_strategies.base import InformeExtraido
from app.services.pdf_strategies.factory import ParserFactory

# Re-exporta os dataclasses para retrocompatibilidade (outros módulos que importam daqui)
from app.services.pdf_strategies.base import (  # noqa: F401
    RendimentoExtraido,
    SaldoExtraido,
    RendimentoTrabalhoExtraido,
    DespesaMedicaExtraido,
)

logger = logging.getLogger(__name__)

TWO_PLACES = Decimal("0.01")


# ─── Resultado de Importação ──────────────────────────────────────────────────

@dataclass
class InformeImportResult:
    """Resultado final: extração + persistência."""
    tipo_informe: str = "banco_corretora"
    cnpj_fonte: str | None = None
    razao_social: str | None = None
    ano_calendario: int | None = None
    estrategia_usada: str = "Desconhecida"
    rendimentos_inseridos: int = 0
    saldos_atualizados: int = 0
    erros: list[str] = field(default_factory=list)
    rendimentos_detalhe: list[dict] = field(default_factory=list)
    saldos_detalhe: list[dict] = field(default_factory=list)
    rendimento_trabalho_detalhe: dict | None = None
    despesas_medicas_detalhe: list[dict] = field(default_factory=list)


# ─── Extração de Texto ────────────────────────────────────────────────────────

def _normalize_text(raw: str) -> str:
    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in text.split("\n")]
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


def extract_text_from_pdf(source: BinaryIO | bytes) -> str:
    """Extrai todo o texto de um PDF usando pdfplumber."""
    if isinstance(source, bytes):
        source = io.BytesIO(source)
    full_text: list[str] = []
    with pdfplumber.open(source) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                full_text.append(text)
    return "\n\n".join(full_text)


# ─── Ponto de entrada testável (sem pdfplumber) ───────────────────────────────

def parse_informe_text(text: str) -> InformeExtraido:
    """
    Ponto de entrada público para parsing de texto já extraído.
    Usa a ParserFactory para selecionar a estratégia correta.

    É a função núcleo testável sem depender de pdfplumber.
    """
    normalized = _normalize_text(text)
    strategy = ParserFactory.get_strategy(normalized)
    logger.info("parse_informe_text: usando estratégia '%s'", strategy.nome_instituicao)
    return strategy.parse(normalized)


# ─── Persistência ─────────────────────────────────────────────────────────────

def _persist_rendimentos(informe: InformeExtraido, contribuinte_id: int, db: Session) -> int:
    if not informe.cnpj_fonte or not informe.razao_social or not informe.ano_calendario:
        return 0
    count = 0
    for rend in informe.rendimentos:
        db.add(RendimentoInforme(
            contribuinte_id=contribuinte_id,
            cnpj_fonte=informe.cnpj_fonte,
            razao_social_fonte=informe.razao_social,
            ano_calendario=informe.ano_calendario,
            categoria=rend.categoria,
            descricao=rend.descricao,
            valor=rend.valor,
            irrf=rend.irrf,
        ))
        count += 1
    if count:
        db.flush()
    return count


def _persist_saldos(informe: InformeExtraido, contribuinte_id: int, db: Session) -> int:
    if not informe.cnpj_fonte or not informe.razao_social:
        return 0

    saldos_por_tipo: dict[str, dict[int, Decimal]] = {}
    for saldo in informe.saldos:
        saldos_por_tipo.setdefault(saldo.tipo_conta, {})[saldo.ano] = saldo.valor

    ano_ref = informe.ano_calendario or max((s.ano for s in informe.saldos), default=2025)
    count = 0

    for tipo_conta, saldos_ano in saldos_por_tipo.items():
        tipo_db = tipo_conta if tipo_conta in ("corrente", "poupanca", "investimento", "corretora") else "investimento"
        saldo_anterior = saldos_ano.get(ano_ref - 1, Decimal("0.00"))
        saldo_atual = saldos_ano.get(ano_ref, Decimal("0.00"))

        existing = db.scalars(
            select(ContaBancaria).where(
                ContaBancaria.contribuinte_id == contribuinte_id,
                ContaBancaria.instituicao == informe.razao_social,
                ContaBancaria.tipo_conta == tipo_db,
                ContaBancaria.ano_referencia == ano_ref,
            )
        ).first()

        if existing:
            existing.saldo_31_12_anterior = saldo_anterior
            existing.saldo_31_12_atual = saldo_atual
        else:
            db.add(ContaBancaria(
                contribuinte_id=contribuinte_id,
                instituicao=informe.razao_social,
                tipo_conta=tipo_db,
                saldo_31_12_anterior=saldo_anterior,
                saldo_31_12_atual=saldo_atual,
                ano_referencia=ano_ref,
            ))
        count += 1

    if count:
        db.flush()
    return count


# ─── Pipeline Principal ───────────────────────────────────────────────────────

def ingest_informe_pdf(
    file_content: BinaryIO,
    contribuinte_id: int,
    db: Session,
) -> InformeImportResult:
    """
    Orquestra o pipeline completo: PDF → texto → parse (Strategy) → persist.
    Chamada pela rota POST /upload/informe-pdf.
    """
    result = InformeImportResult()

    contrib = db.get(Contribuinte, contribuinte_id)
    if contrib is None:
        result.erros.append(f"Contribuinte id={contribuinte_id} não encontrado.")
        return result

    try:
        text = extract_text_from_pdf(file_content)
    except Exception as e:
        result.erros.append(f"Erro ao extrair texto do PDF: {e}")
        return result

    if not text.strip():
        result.erros.append("O PDF não contém texto extraível (pode ser escaneado).")
        return result

    # Seleciona estratégia e faz o parse
    strategy = ParserFactory.get_strategy(text)
    informe = strategy.parse(_normalize_text(text))

    result.tipo_informe = informe.tipo_informe
    result.cnpj_fonte = informe.cnpj_fonte
    result.razao_social = informe.razao_social
    result.ano_calendario = informe.ano_calendario
    result.estrategia_usada = strategy.nome_instituicao
    result.erros.extend(informe.erros)

    if informe.tipo_informe == "trabalho_assalariado":
        if informe.rendimento_trabalho:
            db.add(RendimentoTrabalho(
                contribuinte_id=contribuinte_id,
                cnpj_fonte=informe.cnpj_fonte or "00.000.000/0000-00",
                razao_social_fonte=informe.razao_social or "Empresa Desconhecida",
                ano_calendario=informe.ano_calendario or 2024,
                rendimento_tributavel=informe.rendimento_trabalho.rendimento_tributavel,
                contribuicao_previdenciaria=informe.rendimento_trabalho.contribuicao_previdenciaria,
                irrf=informe.rendimento_trabalho.irrf,
            ))
            result.rendimentos_inseridos += 1
            result.rendimento_trabalho_detalhe = {
                "rendimento_tributavel": str(informe.rendimento_trabalho.rendimento_tributavel),
                "contribuicao_previdenciaria": str(informe.rendimento_trabalho.contribuicao_previdenciaria),
                "irrf": str(informe.rendimento_trabalho.irrf),
            }

        for saude in informe.despesas_medicas:
            db.add(DespesaMedica(
                contribuinte_id=contribuinte_id,
                cnpj_prestador=saude.cnpj_prestador,
                razao_social_prestador=saude.razao_social_prestador,
                ano_calendario=informe.ano_calendario or 2024,
                valor_pago=saude.valor_pago,
            ))
            result.despesas_medicas_detalhe.append({
                "cnpj_prestador": saude.cnpj_prestador,
                "nome_prestador": saude.razao_social_prestador,
                "valor_pago": str(saude.valor_pago),
            })
    else:
        result.rendimentos_inseridos = _persist_rendimentos(informe, contribuinte_id, db)
        result.rendimentos_detalhe = [
            {"categoria": r.categoria, "descricao": r.descricao, "valor": str(r.valor), "irrf": str(r.irrf)}
            for r in informe.rendimentos
        ]
        result.saldos_atualizados = _persist_saldos(informe, contribuinte_id, db)
        result.saldos_detalhe = [
            {"tipo_conta": s.tipo_conta, "ano": s.ano, "valor": str(s.valor)}
            for s in informe.saldos
        ]

    db.commit()
    return result
