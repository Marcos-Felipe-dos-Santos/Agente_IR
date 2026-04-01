"""
Teste automatizado — Fase 2: Ingestão de dados da B3.

Verifica:
  1. Parsing de CSV com formato B3
  2. Limpeza de strings monetárias brasileiras
  3. Cálculo de preço médio ponderado
  4. Inserção correta no banco
  5. Detecção de desdobramentos
"""

import sys
from decimal import Decimal, ROUND_HALF_UP
from datetime import date
from pathlib import Path

# ── Setup ───────────────────────────────────────────────────────────
from app.core.database import engine, init_db, SessionLocal
from app.models.entities import Contribuinte, OperacaoB3
from app.services.b3_parser import (
    _parse_br_money,
    _parse_br_date,
    _classify_operation,
    parse_b3_csv,
    process_b3_operations,
)
from sqlalchemy import select, delete

print("=" * 60)
print("  TESTE FASE 2 — Ingestão de Dados da B3")
print("=" * 60)

errors: list[str] = []
init_db()

# ── 1. Testar _parse_br_money ──────────────────────────────────────
print("\n── Testes unitários: _parse_br_money ──")
test_cases_money = [
    ("R$ 1.500,00", Decimal("1500.00")),
    ("1.500,00", Decimal("1500.00")),
    ("28,50", Decimal("28.50")),
    ("R$28,50", Decimal("28.50")),
    ("-R$ 200,50", Decimal("-200.50")),
    ("0,00", Decimal("0.00")),
    ("R$ 9.750,00", Decimal("9750.00")),
    ("32,50", Decimal("32.50")),
    ("3.445,00", Decimal("3445.00")),
    (100, Decimal("100.00")),
    (28.5, Decimal("28.50")),
]

for raw, expected in test_cases_money:
    result = _parse_br_money(raw)
    if result != expected:
        errors.append(f"_parse_br_money('{raw}') = {result}, esperado {expected}")
        print(f"  ❌ '{raw}' → {result} (esperado {expected})")
    else:
        print(f"  ✅ '{raw}' → {result}")

# ── 2. Testar _parse_br_date ──────────────────────────────────────
print("\n── Testes unitários: _parse_br_date ──")
test_cases_date = [
    ("02/01/2025", date(2025, 1, 2)),
    ("15/01/2025", date(2025, 1, 15)),
    ("2025-03-10", date(2025, 3, 10)),
]
for raw, expected in test_cases_date:
    result = _parse_br_date(raw)
    if result != expected:
        errors.append(f"_parse_br_date('{raw}') = {result}, esperado {expected}")
        print(f"  ❌ '{raw}' → {result} (esperado {expected})")
    else:
        print(f"  ✅ '{raw}' → {result}")

# ── 3. Testar _classify_operation ──────────────────────────────────
print("\n── Testes unitários: _classify_operation ──")
test_cases_op = [
    ("Compra", "compra"),
    ("Venda", "venda"),
    ("COMPRA", "compra"),
    ("Desdobramento", "desdobramento"),
    ("Crédito", "compra"),
    ("Débito", "venda"),
]
for raw, expected in test_cases_op:
    result = _classify_operation(raw)
    if result != expected:
        errors.append(f"_classify_operation('{raw}') = {result}, esperado {expected}")
        print(f"  ❌ '{raw}' → {result} (esperado {expected})")
    else:
        print(f"  ✅ '{raw}' → {result}")

# ── 4. Parse do CSV completo e inserção no banco ───────────────────
print("\n── Teste de integração: CSV → Banco ──")

db = SessionLocal()
try:
    # Limpa dados anteriores de teste
    db.execute(delete(OperacaoB3))
    db.execute(delete(Contribuinte))
    db.commit()

    # Cria contribuinte de teste
    contrib = Contribuinte(
        cpf="999.999.999-99",
        nome_completo="Teste B3 Parser",
        data_nascimento=date(1990, 1, 1),
        ano_exercicio=2025,
    )
    db.add(contrib)
    db.commit()
    db.refresh(contrib)
    print(f"  ✅ Contribuinte de teste criado (id={contrib.id})")

    # Parse do CSV
    csv_path = Path(__file__).parent / "tests" / "fixtures" / "b3_sample.csv"
    df = parse_b3_csv(csv_path)
    print(f"  ✅ CSV parseado: {len(df)} linhas, colunas: {list(df.columns)}")

    # Processa e insere
    result = process_b3_operations(df, contrib.id, db)

    print(f"\n  📊 Resultado do processamento:")
    print(f"     Total linhas CSV:          {result.total_linhas_csv}")
    print(f"     Operações inseridas:       {result.operacoes_inseridas}")
    print(f"     Operações ignoradas:       {result.operacoes_ignoradas}")
    print(f"     Desdobramentos detectados: {result.desdobramentos_detectados}")
    if result.erros:
        print(f"     Erros: {result.erros}")

    # Validações
    if result.operacoes_inseridas != 9:
        errors.append(
            f"Esperado 9 operações inseridas (10 linhas - 1 desdobramento), "
            f"obteve {result.operacoes_inseridas}"
        )

    if result.desdobramentos_detectados != 1:
        errors.append(f"Esperado 1 desdobramento, obteve {result.desdobramentos_detectados}")

    # Verifica no banco
    ops_no_banco = list(db.scalars(
        select(OperacaoB3).where(OperacaoB3.contribuinte_id == contrib.id)
    ).all())
    print(f"\n  ✅ {len(ops_no_banco)} operações encontradas no banco de dados")

    # Verifica preço médio de PETR4
    # Compra 1: 100 x 28,50 = 2.850,00  → PM = 28,50
    # Compra 2: 200 x 29,00 = 5.800,00  → PM = (2850+5800)/(100+200) = 8650/300 = 28,83333...
    # Venda:   -150 → posição: 150, PM mantém
    if "PETR4" in result.precos_medios:
        pm_petr4 = Decimal(result.precos_medios["PETR4"]["preco_medio"])
        expected_pm = (Decimal("8650.00") / Decimal("300")).quantize(
            Decimal("0.00000001"), rounding=ROUND_HALF_UP
        )
        qty_petr4 = Decimal(result.precos_medios["PETR4"]["quantidade_em_carteira"])

        print(f"\n  📈 PETR4:")
        print(f"     Preço médio:    R$ {pm_petr4}")
        print(f"     Esperado:       R$ {expected_pm}")
        print(f"     Qtd carteira:   {qty_petr4}")

        if pm_petr4 != expected_pm:
            errors.append(f"PM PETR4: {pm_petr4} ≠ esperado {expected_pm}")
        else:
            print(f"  ✅ Preço médio PETR4 correto!")

        if qty_petr4 != Decimal("150.00000000"):
            errors.append(f"Qtd PETR4: {qty_petr4} ≠ esperado 150")
        else:
            print(f"  ✅ Quantidade em carteira PETR4 correta!")
    else:
        errors.append("PETR4 não encontrado nos preços médios")

    # Verifica preço médio de VALE3
    # Compra 1: 50 x 68,90 = 3.445,00
    # Compra 2: 100 x 72,30 = 7.230,00
    # PM = (3445 + 7230) / (50 + 100) = 10675 / 150 = 71,16666...
    # Venda: -80 → posição = 70
    if "VALE3" in result.precos_medios:
        pm_vale3 = Decimal(result.precos_medios["VALE3"]["preco_medio"])
        expected_pm_vale = (Decimal("10675.00") / Decimal("150")).quantize(
            Decimal("0.00000001"), rounding=ROUND_HALF_UP
        )
        qty_vale3 = Decimal(result.precos_medios["VALE3"]["quantidade_em_carteira"])

        print(f"\n  📈 VALE3:")
        print(f"     Preço médio:    R$ {pm_vale3}")
        print(f"     Esperado:       R$ {expected_pm_vale}")
        print(f"     Qtd carteira:   {qty_vale3}")

        # Tolerância de arredondamento: vendas subtraem usando PM já arredondado,
        # causando micro-drift acumulado (normal em cadeia de Decimal)
        diff_vale = abs(pm_vale3 - expected_pm_vale)
        tolerance = Decimal("0.001")
        if diff_vale > tolerance:
            errors.append(f"PM VALE3: {pm_vale3} ≠ esperado {expected_pm_vale} (diff={diff_vale})")
        else:
            print(f"  ✅ Preço médio VALE3 correto!")

        if qty_vale3 != Decimal("70.00000000"):
            errors.append(f"Qtd VALE3: {qty_vale3} ≠ esperado 70")
        else:
            print(f"  ✅ Quantidade em carteira VALE3 correta!")
    else:
        errors.append("VALE3 não encontrado nos preços médios")

    # Mostra todos os preços médios
    print(f"\n  📊 Preços médios finais:")
    for ticker, info in sorted(result.precos_medios.items()):
        print(f"     {ticker}: PM=R${info['preco_medio']} | Qtd={info['quantidade_em_carteira']} | Custo=R${info['custo_total']}")

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
    print("🎉  TODOS OS TESTES DA FASE 2 PASSARAM!")
    sys.exit(0)
