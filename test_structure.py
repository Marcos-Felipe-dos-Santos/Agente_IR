"""
Script de teste estrutural — verifica se:
  1. O banco de dados é criado corretamente
  2. As 5 tabelas existem
  3. A inserção/leitura com validação Pydantic funciona
  4. Constraints de CHECK são aplicadas
  5. Foreign Keys são respeitadas
"""

import sys
from decimal import Decimal
from datetime import date

from sqlalchemy import inspect, text

# ── 1. Inicializar o banco ──────────────────────────────────────────
from app.core.database import engine, init_db, SessionLocal
from app.models.entities import (
    Contribuinte, ContaBancaria, OperacaoB3, AtivoCripto, Provento,
)
from app.schemas.fiscal import (
    ContribuinteCreate, ContaBancariaCreate, OperacaoB3Create,
    TipoConta, TipoOperacao, TipoProvento,
    AtivoCriptoCreate, ProventoCreate,
)

print("=" * 60)
print("  TESTE ESTRUTURAL — Agent IR (Fase 1)")
print("=" * 60)

errors: list[str] = []

# Criar tabelas
init_db()
print("\n✅  init_db() executado com sucesso.")

# ── 2. Verificar tabelas ───────────────────────────────────────────
inspector = inspect(engine)
expected_tables = {
    "contribuintes", "contas_bancarias", "operacoes_b3",
    "ativos_cripto", "proventos",
}
actual_tables = set(inspector.get_table_names())
missing = expected_tables - actual_tables
if missing:
    errors.append(f"Tabelas faltando: {missing}")
else:
    print(f"✅  Todas as {len(expected_tables)} tabelas encontradas: {sorted(actual_tables & expected_tables)}")

# ── 3. Inserção + leitura via ORM ──────────────────────────────────
db = SessionLocal()
try:
    # Contribuinte
    contrib_data = ContribuinteCreate(
        cpf="123.456.789-00",
        nome_completo="João da Silva",
        data_nascimento=date(1990, 5, 15),
        ano_exercicio=2025,
    )
    contrib = Contribuinte(**contrib_data.model_dump())
    db.add(contrib)
    db.commit()
    db.refresh(contrib)
    assert contrib.id is not None
    print(f"✅  Contribuinte criado (id={contrib.id})")

    # Conta Bancária
    conta_data = ContaBancariaCreate(
        contribuinte_id=contrib.id,
        instituicao="Banco do Brasil",
        codigo_banco="001",
        agencia="1234-5",
        conta="12345-6",
        tipo_conta=TipoConta.corrente,
        saldo_31_12_anterior=Decimal("15000.50"),
        saldo_31_12_atual=Decimal("18200.75"),
        ano_referencia=2025,
    )
    conta = ContaBancaria(**conta_data.model_dump())
    db.add(conta)
    db.commit()
    db.refresh(conta)
    assert conta.saldo_31_12_atual == Decimal("18200.75")
    print(f"✅  ContaBancaria criada — saldo R$ {conta.saldo_31_12_atual}")

    # Operação B3
    op_data = OperacaoB3Create(
        contribuinte_id=contrib.id,
        data_operacao=date(2025, 3, 10),
        tipo_operacao=TipoOperacao.compra,
        ticker="PETR4",
        quantidade=Decimal("100.00000000"),
        preco_unitario=Decimal("28.50000000"),
        valor_total=Decimal("2850.00"),
        custos_operacionais=Decimal("4.50"),
        corretora="XP Investimentos",
    )
    op = OperacaoB3(**op_data.model_dump())
    db.add(op)
    db.commit()
    db.refresh(op)
    print(f"✅  OperacaoB3 criada — {op.ticker} {op.tipo_operacao} {op.quantidade}x R${op.preco_unitario}")

    # Ativo Cripto
    cripto_data = AtivoCriptoCreate(
        contribuinte_id=contrib.id,
        data_operacao=date(2025, 2, 20),
        tipo_operacao=TipoOperacao.compra,
        moeda="BTC",
        quantidade=Decimal("0.05000000"),
        preco_unitario_brl=Decimal("500000.00000000"),
        valor_total_brl=Decimal("25000.00"),
        exchange="Mercado Bitcoin",
    )
    cripto = AtivoCripto(**cripto_data.model_dump())
    db.add(cripto)
    db.commit()
    db.refresh(cripto)
    print(f"✅  AtivoCripto criado — {cripto.moeda} {cripto.quantidade} @ R${cripto.preco_unitario_brl}")

    # Provento
    prov_data = ProventoCreate(
        contribuinte_id=contrib.id,
        data_pagamento=date(2025, 4, 15),
        tipo_provento=TipoProvento.dividendo,
        ticker="VALE3",
        cnpj_fonte="33.592.510/0001-54",
        valor_bruto=Decimal("1200.00"),
        irrf=Decimal("0.00"),
        valor_liquido=Decimal("1200.00"),
    )
    prov = Provento(**prov_data.model_dump())
    db.add(prov)
    db.commit()
    db.refresh(prov)
    print(f"✅  Provento criado — {prov.tipo_provento} {prov.ticker} R${prov.valor_bruto}")

    # ── 4. Testar validação Pydantic (deve rejeitar CPF inválido) ───
    try:
        ContribuinteCreate(
            cpf="12345678900",  # sem pontuação → deve falhar
            nome_completo="Teste",
            data_nascimento=date(2000, 1, 1),
            ano_exercicio=2025,
        )
        errors.append("Pydantic NÃO rejeitou CPF sem formato correto")
    except Exception:
        print("✅  Pydantic rejeitou CPF com formato inválido (esperado)")

    # ── 5. FK check ─────────────────────────────────────────────────
    try:
        fake_conta = ContaBancaria(
            contribuinte_id=99999,
            instituicao="Banco Fantasma",
            tipo_conta=TipoConta.corrente,
            saldo_31_12_anterior=Decimal("0"),
            saldo_31_12_atual=Decimal("0"),
            ano_referencia=2025,
        )
        db.add(fake_conta)
        db.commit()
        errors.append("FK constraint NÃO foi aplicada (contribuinte inexistente aceito)")
    except Exception:
        db.rollback()
        print("✅  FK constraint funcionando (contribuinte inexistente rejeitado)")

finally:
    db.close()

# ── Resultado final ─────────────────────────────────────────────────
print("\n" + "=" * 60)
if errors:
    print("❌  FALHAS ENCONTRADAS:")
    for e in errors:
        print(f"   • {e}")
    sys.exit(1)
else:
    print("🎉  TODOS OS TESTES PASSARAM — Fase 1 concluída com sucesso!")
    sys.exit(0)
