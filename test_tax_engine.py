import pytest
from datetime import date
from decimal import Decimal

from sqlalchemy import delete

from app.core.database import SessionLocal, init_db
from app.models.entities import AtivoCripto, Contribuinte, OperacaoB3
from app.services.tax_engine import (
    LIMITE_ISENCAO_ACOES_MES,
    apurar_meses_b3,
    auditar_cripto_vendas,
)


@pytest.fixture(scope="session", autouse=True)
def setup_database():
    init_db()


@pytest.fixture
def db():
    session = SessionLocal()
    # Limpar banco de teste
    session.execute(delete(OperacaoB3))
    session.execute(delete(AtivoCripto))
    session.execute(delete(Contribuinte))
    session.commit()
    yield session
    session.close()


@pytest.fixture
def contrib_id(db):
    contrib = Contribuinte(
        cpf="000.000.000-00",
        nome_completo="Investidor Teste Engine Pytest",
        data_nascimento=date(1990, 1, 1),
        ano_exercicio=2025,
    )
    db.add(contrib)
    db.commit()
    return contrib.id

def test_engine_b3_completo(db, contrib_id):
    # Setup de dados na Tabela
    # Mês 1: Só compras
    op1 = OperacaoB3(contribuinte_id=contrib_id, data_operacao=date(2024, 1, 15), tipo_operacao="compra", ticker="ITUB4", quantidade=Decimal("100"), preco_unitario=Decimal("30.00"), valor_total=Decimal("3000.00"))
    op2 = OperacaoB3(contribuinte_id=contrib_id, data_operacao=date(2024, 1, 20), tipo_operacao="compra", ticker="VALE3", quantidade=Decimal("200"), preco_unitario=Decimal("80.00"), valor_total=Decimal("16000.00"))
    db.add_all([op1, op2])
    
    # Mês 2: Venda Isenta (Volume de venda 1750 < 20k, Lucro = 250)
    op3 = OperacaoB3(contribuinte_id=contrib_id, data_operacao=date(2024, 2, 10), tipo_operacao="venda", ticker="ITUB4", quantidade=Decimal("50"), preco_unitario=Decimal("35.00"), valor_total=Decimal("1750.00"))
    db.add(op3)

    # Mês 3: Prejuízo
    op4 = OperacaoB3(contribuinte_id=contrib_id, data_operacao=date(2024, 3, 5), tipo_operacao="venda", ticker="VALE3", quantidade=Decimal("100"), preco_unitario=Decimal("70.00"), valor_total=Decimal("7000.00"))
    db.add(op4)

    # Mês 4: Lucro Tributável com absorcao do offset
    op5 = OperacaoB3(contribuinte_id=contrib_id, data_operacao=date(2024, 4, 15), tipo_operacao="venda", ticker="VALE3", quantidade=Decimal("100"), preco_unitario=Decimal("300.00"), valor_total=Decimal("30000.00"))
    db.add(op5)

    db.commit()

    meses_apurados, prej_final = apurar_meses_b3(contrib_id, 2024, db)
    meses_dict = {m["mes"]: m for m in meses_apurados}

    # Asserções Seguras (Decimal e conversao segura)
    assert 2 in meses_dict
    assert Decimal(meses_dict[2]["lucro_isento"]) == Decimal("250.00")
    assert Decimal(meses_dict[2]["lucro_tributavel"]) == Decimal("0.00")

    assert 3 in meses_dict
    assert Decimal(meses_dict[3]["prejuizo_mes_gerado"]) == Decimal("1000.00")
    assert Decimal(meses_dict[3]["prejuizo_a_compensar_seguinte"]) == Decimal("1000.00")

    assert 4 in meses_dict
    assert Decimal(meses_dict[4]["total_vendas"]) == Decimal("30000.00")
    assert Decimal(meses_dict[4]["prejuizo_acumulado_utilizado"]) == Decimal("1000.00")
    assert Decimal(meses_dict[4]["lucro_tributavel"]) == Decimal("21000.00")
    assert Decimal(meses_dict[4]["imposto_devido"]) == Decimal("3150.00")
    assert Decimal(meses_dict[4]["prejuizo_a_compensar_seguinte"]) == Decimal("0.00")

    assert prej_final == Decimal("0.00")


def test_auditoria_cripto_vendas(db, contrib_id):
    # Mês com isenção
    cripto1 = AtivoCripto(contribuinte_id=contrib_id, data_operacao=date(2024, 7, 1), tipo_operacao="venda", moeda="BTC", quantidade=Decimal("0.1"), preco_unitario_brl=Decimal("150000.00"), valor_total_brl=Decimal("15000.00"))
    
    # Mês estourando (Agosto)
    cripto2 = AtivoCripto(contribuinte_id=contrib_id, data_operacao=date(2024, 8, 10), tipo_operacao="venda", moeda="ETH", quantidade=Decimal("10"), preco_unitario_brl=Decimal("2000.00"), valor_total_brl=Decimal("20000.00"))
    cripto3 = AtivoCripto(contribuinte_id=contrib_id, data_operacao=date(2024, 8, 15), tipo_operacao="venda", moeda="SOL", quantidade=Decimal("100"), preco_unitario_brl=Decimal("200.00"), valor_total_brl=Decimal("20000.00"))
    
    db.add_all([cripto1, cripto2, cripto3])
    db.commit()

    alertas = auditar_cripto_vendas(contrib_id, 2024, db)
    assert len(alertas) == 1
    
    al = alertas[0]
    assert al["ano"] == 2024
    assert al["mes"] == 8
    assert Decimal(al["total_vendas"]) == Decimal("40000.00")
    assert Decimal(al["limite_isencao"]) == Decimal("35000.00")
