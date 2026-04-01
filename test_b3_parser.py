"""
Teste Fase 2 — Ingestão de dados da B3 (migrado para pytest).

Verifica:
  1. Parsing de CSV com formato B3
  2. Limpeza de strings monetárias brasileiras
  3. Cálculo de preço médio ponderado
  4. Inserção correta no banco
  5. Detecção de desdobramentos
"""
import pytest
from decimal import Decimal, ROUND_HALF_UP
from datetime import date
from pathlib import Path

from sqlalchemy import select, delete

from app.core.database import engine, init_db, SessionLocal
from app.models.entities import Contribuinte, OperacaoB3
from app.services.b3_parser import (
    _parse_br_money,
    _parse_br_date,
    _classify_operation,
    parse_b3_csv,
    process_b3_operations,
)


@pytest.fixture(scope="session", autouse=True)
def setup_db_b3():
    init_db()


@pytest.fixture
def db_b3():
    session = SessionLocal()
    session.execute(delete(OperacaoB3))
    session.execute(delete(Contribuinte))
    session.commit()
    yield session
    session.close()


@pytest.fixture
def contrib_b3(db_b3):
    contrib = Contribuinte(
        cpf="000.000.001-00",  # CPF fictício para testes
        nome_completo="Teste B3 Parser",
        data_nascimento=date(1990, 1, 1),
        ano_exercicio=2025,
    )
    db_b3.add(contrib)
    db_b3.commit()
    return contrib


# ─── Testes unitários ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("R$ 1.500,00", Decimal("1500.00")),
    ("1.500,00",    Decimal("1500.00")),
    ("28,50",       Decimal("28.50")),
    ("R$28,50",     Decimal("28.50")),
    ("-R$ 200,50",  Decimal("-200.50")),
    ("0,00",        Decimal("0.00")),
    ("R$ 9.750,00", Decimal("9750.00")),
    ("32,50",       Decimal("32.50")),
    ("3.445,00",    Decimal("3445.00")),
])
def test_parse_br_money(raw, expected):
    assert _parse_br_money(raw) == expected


@pytest.mark.parametrize("raw,expected", [
    ("02/01/2025", date(2025, 1, 2)),
    ("15/01/2025", date(2025, 1, 15)),
    ("2025-03-10", date(2025, 3, 10)),
])
def test_parse_br_date(raw, expected):
    assert _parse_br_date(raw) == expected


@pytest.mark.parametrize("raw,expected", [
    ("Compra",        "compra"),
    ("Venda",         "venda"),
    ("COMPRA",        "compra"),
    ("Desdobramento", "desdobramento"),
    ("Crédito",       "compra"),
    ("Débito",        "venda"),
])
def test_classify_operation(raw, expected):
    assert _classify_operation(raw) == expected


# ─── Teste de integração (CSV → Banco) ────────────────────────────────────────

def test_parse_csv_e_insercao_banco(db_b3, contrib_b3):
    csv_path = Path(__file__).parent / "tests" / "fixtures" / "b3_sample.csv"
    if not csv_path.exists():
        pytest.skip(f"Fixture CSV não encontrada: {csv_path}")

    df = parse_b3_csv(csv_path)
    assert len(df) > 0, "CSV não contém linhas"

    result = process_b3_operations(df, contrib_b3.id, db_b3)

    assert result.operacoes_inseridas == 9, (
        f"Esperado 9 operações, obteve {result.operacoes_inseridas}. Erros: {result.erros}"
    )
    assert result.desdobramentos_detectados == 1


def test_preco_medio_petr4(db_b3, contrib_b3):
    csv_path = Path(__file__).parent / "tests" / "fixtures" / "b3_sample.csv"
    if not csv_path.exists():
        pytest.skip(f"Fixture CSV não encontrada: {csv_path}")

    df = parse_b3_csv(csv_path)
    result = process_b3_operations(df, contrib_b3.id, db_b3)

    assert "PETR4" in result.precos_medios, "PETR4 não encontrado nos preços médios"

    pm = Decimal(str(result.precos_medios["PETR4"]["preco_medio"]))
    expected = (Decimal("8650.00") / Decimal("300")).quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP)
    assert pm == expected, f"PM PETR4: {pm} ≠ esperado {expected}"

    qty = Decimal(str(result.precos_medios["PETR4"]["quantidade_em_carteira"]))
    assert qty == Decimal("150.00000000"), f"Qtd PETR4: {qty} ≠ 150"


def test_preco_medio_vale3(db_b3, contrib_b3):
    csv_path = Path(__file__).parent / "tests" / "fixtures" / "b3_sample.csv"
    if not csv_path.exists():
        pytest.skip(f"Fixture CSV não encontrada: {csv_path}")

    df = parse_b3_csv(csv_path)
    result = process_b3_operations(df, contrib_b3.id, db_b3)

    assert "VALE3" in result.precos_medios, "VALE3 não encontrado nos preços médios"

    pm = Decimal(str(result.precos_medios["VALE3"]["preco_medio"]))
    expected = (Decimal("10675.00") / Decimal("150")).quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP)
    diff = abs(pm - expected)
    assert diff <= Decimal("0.001"), f"PM VALE3: {pm} ≠ esperado {expected} (diff={diff})"

    qty = Decimal(str(result.precos_medios["VALE3"]["quantidade_em_carteira"]))
    assert qty == Decimal("70.00000000"), f"Qtd VALE3: {qty} ≠ 70"
