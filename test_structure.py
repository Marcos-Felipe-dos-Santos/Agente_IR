"""
Teste Estrutural — verifica criação do banco, tabelas, ORM, Pydantic e constraints.
(Migrado de script sys.exit para pytest.)
"""
import pytest
from decimal import Decimal
from datetime import date

from sqlalchemy import inspect

from app.core.database import engine, init_db, SessionLocal
from app.models.entities import (
    Contribuinte, ContaBancaria, OperacaoB3, AtivoCripto, Provento,
)
from app.schemas.fiscal import (
    ContribuinteCreate, ContaBancariaCreate, OperacaoB3Create,
    TipoConta, TipoOperacao, TipoProvento,
    AtivoCriptoCreate, ProventoCreate,
)


@pytest.fixture(scope="session", autouse=True)
def setup_db_structure():
    init_db()


# ─── Testes de Schema────────────────────────────────────────────────────────

def test_tabelas_existem():
    inspector = inspect(engine)
    expected = {"contribuintes", "contas_bancarias", "operacoes_b3", "ativos_cripto", "proventos"}
    actual = set(inspector.get_table_names())
    missing = expected - actual
    assert not missing, f"Tabelas faltando: {missing}"


def test_pydantic_rejeita_cpf_sem_formatacao():
    """CPF '12345678900' (sem pontuação) deve ser rejeitado pelo schema Pydantic."""
    with pytest.raises(Exception):
        ContribuinteCreate(
            cpf="12345678900",  # inválido: sem pontuação — teste de rejeição
            nome_completo="Teste",
            data_nascimento=date(2000, 1, 1),
            ano_exercicio=2025,
        )


# ─── Teste de integração ORM ──────────────────────────────────────────────────

@pytest.fixture
def db_structure():
    session = SessionLocal()
    yield session
    session.rollback()
    session.close()


def test_insercao_contribuinte(db_structure):
    contrib = Contribuinte(
        cpf="000.000.002-00",  # CPF fictício de teste
        nome_completo="QA Teste Estrutural",
        data_nascimento=date(1990, 5, 15),
        ano_exercicio=2025,
    )
    db_structure.add(contrib)
    db_structure.commit()
    assert contrib.id is not None


def test_insercao_conta_bancaria(db_structure):
    contrib = Contribuinte(
        cpf="000.000.003-00",
        nome_completo="QA Conta Bancaria",
        data_nascimento=date(1990, 5, 15),
        ano_exercicio=2025,
    )
    db_structure.add(contrib)
    db_structure.commit()

    conta = ContaBancaria(
        contribuinte_id=contrib.id,
        instituicao="Banco do Brasil",
        tipo_conta=TipoConta.corrente,
        saldo_31_12_anterior=Decimal("15000.50"),
        saldo_31_12_atual=Decimal("18200.75"),
        ano_referencia=2025,
    )
    db_structure.add(conta)
    db_structure.commit()
    assert Decimal(str(conta.saldo_31_12_atual)) == Decimal("18200.75")


def test_fk_constraint_contribuinte_inexistente(db_structure):
    """FK deve rejeitar conta bancária com contribuinte_id fantasma."""
    with pytest.raises(Exception):
        fake = ContaBancaria(
            contribuinte_id=99999,
            instituicao="Banco Fantasma",
            tipo_conta=TipoConta.corrente,
            saldo_31_12_anterior=Decimal("0"),
            saldo_31_12_atual=Decimal("0"),
            ano_referencia=2025,
        )
        db_structure.add(fake)
        db_structure.commit()
