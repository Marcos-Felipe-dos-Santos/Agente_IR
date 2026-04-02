"""
Teste Fase 3 — Parser de Informe de Rendimentos PDF (migrado para pytest).
"""
import pytest
from datetime import date
from decimal import Decimal

from sqlalchemy import delete, select

from app.core.database import init_db, SessionLocal
from app.models.entities import ContaBancaria, Contribuinte, RendimentoInforme
from app.services.pdf_parser import parse_informe_text, _persist_rendimentos, _persist_saldos
from app.services.pdf_strategies.generic import (
    _parse_br_money,
    _extract_cnpj_raw as _extract_cnpj,
    _extract_razao_social_raw as _extract_razao_social,
    _extract_rendimentos_from_section,
    _extract_saldos_from_text,
)

@pytest.fixture(scope="module")
def db_pdf_engine():
    init_db()
    db = SessionLocal()
    yield db
    db.close()


@pytest.fixture(scope="module")
def contribuinte_pdf(db_pdf_engine):
    db = db_pdf_engine
    db.execute(delete(RendimentoInforme))
    db.execute(delete(ContaBancaria))
    db.execute(delete(Contribuinte))
    db.commit()

    contrib = Contribuinte(
        cpf="000.000.004-00",
        nome_completo="Teste PDF Parser",
        data_nascimento=date(1985, 3, 20),
        ano_exercicio=2025,
    )
    db.add(contrib)
    db.commit()
    cid = contrib.id

    yield contrib

    db.execute(delete(RendimentoInforme))
    db.execute(delete(ContaBancaria))
    db.execute(delete(Contribuinte))
    db.commit()


MOCK_INFORME = """
INFORME DE RENDIMENTOS FINANCEIROS
ANO-CALENDÁRIO DE 2024

1. FONTE PAGADORA
CNPJ: 00.000.000/0001-91
RAZÃO SOCIAL: BANCO DO BRASIL S.A.

3. RENDIMENTOS SUJEITOS À TRIBUTAÇÃO EXCLUSIVA/DEFINITIVA
Tipo de Rendimento                                    Valor (R$)
Rendimentos de operações financeiras (CDB, RDB)       1.234,56
Rendimentos de Fundos de Investimento                   890,00

4. RENDIMENTOS ISENTOS E NÃO TRIBUTÁVEIS
Tipo de Rendimento                                    Valor (R$)
Rendimentos de caderneta de poupança                    567,89
LCI - Letra de Crédito Imobiliário                    2.345,67
LCA - Letra de Crédito do Agronegócio                   450,00

6. INFORMAÇÕES COMPLEMENTARES

Conta Corrente
Saldo em 31/12/2023: R$ 15.000,00
Saldo em 31/12/2024: R$ 18.500,00

Poupança
Saldo em 31/12/2023: R$ 5.000,00
Saldo em 31/12/2024: R$ 5.567,89
"""

MOCK_INFORME_QUEBRADO = """INFORME DE RENDIMENTOS
FINANCEIROS

ANO-CALENDÁRIO
DE 2024

CNPJ/MF:
33.592.510/0001-54

NOME EMPRESARIAL:
XP INVESTIMENTOS CCTVM S.A.

3 - RENDIMENTOS SUJEITOS À TRIBUTAÇÃO
EXCLUSIVA/DEFINITIVA

Rendimentos de CDB  3.500,00

4 - RENDIMENTOS ISENTOS E NÃO
TRIBUTÁVEIS

LCI  1.200,00
LCA  800,00

5 - INFORMAÇÕES COMPLEMENTARES

Conta Corrente
31/12/2023  2.500,00
31/12/2024  3.800,00
"""

@pytest.mark.parametrize("raw,expected", [
    ("R$ 1.500,00",  Decimal("1500.00")),
    ("1.234,56",     Decimal("1234.56")),
    ("R$28,50",      Decimal("28.50")),
    ("15.000,00",    Decimal("15000.00")),
    ("567,89",       Decimal("567.89")),
    ("0,00",         Decimal("0.00")),
    ("-R$ 100,00",   Decimal("-100.00")),
    ("18.500,00",    Decimal("18500.00")),
    ("",             None),
    ("-",            None),
])
def test_parse_br_money(raw, expected):
    assert _parse_br_money(raw) == expected

@pytest.mark.parametrize("text,expected", [
    ("CNPJ: 00.000.000/0001-91",          "00.000.000/0001-91"),
    ("CNPJ/MF: 33.592.510/0001-54",       "33.592.510/0001-54"),
    ("CNPJ:\n00.000.000/0001-91",         "00.000.000/0001-91"),
    ("CNPJ :  33.592.510/0001-54",        "33.592.510/0001-54"),
    ("Documento sem CNPJ aqui",           None),
])
def test_extract_cnpj(text, expected):
    assert _extract_cnpj(text) == expected

@pytest.mark.parametrize("text,expected", [
    ("RAZÃO SOCIAL: BANCO DO BRASIL S.A.\nCNPJ",                "BANCO DO BRASIL S.A"),
    ("NOME EMPRESARIAL: XP INVESTIMENTOS CCTVM S.A.\nOutra",    "XP INVESTIMENTOS CCTVM S.A"),
    ("FONTE PAGADORA: ITAÚ UNIBANCO S.A.\n",                    "ITAÚ UNIBANCO S.A"),
    ("Texto sem razao social",                                   None),
])
def test_extract_razao_social(text, expected):
    assert _extract_razao_social(text) == expected


def test_parse_informe_cabecalho():
    result = parse_informe_text(MOCK_INFORME)
    assert result.cnpj_fonte == "00.000.000/0001-91"
    assert result.razao_social == "BANCO DO BRASIL S.A"
    assert result.ano_calendario == 2024

def test_parse_informe_rendimentos_tributacao_exclusiva():
    result = parse_informe_text(MOCK_INFORME)
    trib = [r for r in result.rendimentos if r.categoria == "tributacao_exclusiva"]
    assert len(trib) >= 2

def test_parse_informe_rendimentos_isentos():
    result = parse_informe_text(MOCK_INFORME)
    isentos = [r for r in result.rendimentos if r.categoria == "isento"]
    assert len(isentos) >= 2

def test_parse_informe_saldos():
    result = parse_informe_text(MOCK_INFORME)
    assert len(result.saldos) >= 2

def test_parse_informe_quebrado_resiliencia():
    result = parse_informe_text(MOCK_INFORME_QUEBRADO)
    assert result.cnpj_fonte == "33.592.510/0001-54"
    assert result.ano_calendario == 2024
    assert result.razao_social is not None
    assert len(result.rendimentos) >= 2
    assert len(result.saldos) >= 2

def test_persistencia_rendimentos(db_pdf_engine, contribuinte_pdf):
    informe = parse_informe_text(MOCK_INFORME)
    count = _persist_rendimentos(informe, contribuinte_pdf.id, db_pdf_engine)
    db_pdf_engine.commit()

    rends_db = list(db_pdf_engine.scalars(
        select(RendimentoInforme).where(RendimentoInforme.contribuinte_id == contribuinte_pdf.id)
    ).all())
    assert len(rends_db) == count

def test_persistencia_saldos_corrente(db_pdf_engine, contribuinte_pdf):
    informe = parse_informe_text(MOCK_INFORME)
    _persist_saldos(informe, contribuinte_pdf.id, db_pdf_engine)
    db_pdf_engine.commit()

    contas = list(db_pdf_engine.scalars(
        select(ContaBancaria).where(ContaBancaria.contribuinte_id == contribuinte_pdf.id)
    ).all())
    assert len(contas) >= 1

    corrente = next((c for c in contas if c.tipo_conta == "corrente"), None)
    assert corrente is not None
    assert Decimal(str(corrente.saldo_31_12_anterior)) == Decimal("15000.00")
    assert Decimal(str(corrente.saldo_31_12_atual)) == Decimal("18500.00")
