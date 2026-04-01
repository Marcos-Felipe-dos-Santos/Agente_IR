"""
Testes para o Motor de Apuração Tributária (O Cérebro).
"""

import sys
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

# Como defini no tax engine:
# LIMITE_ISENCAO_ACOES_MES = 20000.00
# LIMITE_ISENCAO_CRIPTO_MES = 35000.00

errors = []


def debug_assert(condition: bool, message: str) -> None:
    if not condition:
        errors.append(message)
        print(f"  ❌ {message}")
    else:
        print(f"  ✅ {message.split(' (')[0]}")


def run_tests():
    print("=" * 60)
    print("  TESTE FASE 4 — MOTOR DE APURAÇÃO TRIBUTÁRIA")
    print("=" * 60)

    init_db()
    db = SessionLocal()

    try:
        # Limpar banco de teste
        db.execute(delete(OperacaoB3))
        db.execute(delete(AtivoCripto))
        db.execute(delete(Contribuinte))
        db.commit()

        # ── Setup Contribuinte ───────────────────────────────────
        contrib = Contribuinte(
            cpf="999.999.999-99",
            nome_completo="Investidor Teste Engine",
            data_nascimento=date(1990, 1, 1),
            ano_exercicio=2025,
        )
        db.add(contrib)
        db.commit()
        db.refresh(contrib)
        cid = contrib.id

        print("\n── 1. População de Dados (B3 Swing Trade) ──")

        # Mês 1 (Janeiro): Só compras
        op1 = OperacaoB3(
            contribuinte_id=cid,
            data_operacao=date(2024, 1, 15),
            tipo_operacao="compra",
            ticker="ITUB4",
            quantidade=Decimal("100"),
            preco_unitario=Decimal("30.00"),  # Custo = 3000
            valor_total=Decimal("3000.00"),
        )

        op2 = OperacaoB3(
            contribuinte_id=cid,
            data_operacao=date(2024, 1, 20),
            tipo_operacao="compra",
            ticker="VALE3",
            quantidade=Decimal("200"),
            preco_unitario=Decimal("80.00"),  # Custo = 16000
            valor_total=Decimal("16000.00"),
        )
        db.add_all([op1, op2])
        
        # Mês 2 (Fevereiro): Lucro ISENTO (< 20k)
        # Vende 50 ITUB4 a 35,00 (Lucro de 5,00/ação = 250,00) -> Vol: 1750,00
        op3 = OperacaoB3(
            contribuinte_id=cid,
            data_operacao=date(2024, 2, 10),
            tipo_operacao="venda",
            ticker="ITUB4",
            quantidade=Decimal("50"),
            preco_unitario=Decimal("35.00"),
            valor_total=Decimal("1750.00"),
        )
        db.add(op3)

        # Mês 3 (Março): Prejuízo (Vendas < 20k ou não, prejuízo anota igual)
        # Vende 100 VALE3 a 70,00 (Prejuízo de 10,00/ação = 1000,00)
        op4 = OperacaoB3(
            contribuinte_id=cid,
            data_operacao=date(2024, 3, 5),
            tipo_operacao="venda",
            ticker="VALE3",
            quantidade=Decimal("100"),
            preco_unitario=Decimal("70.00"),
            valor_total=Decimal("7000.00"),
        )
        db.add(op4)

        # Mês 4 (Abril): Lucro Tributável com Compensação
        # Vende 100 VALE3 a R$ 300,00 (Lucro de 220,00/ação = 22.000,00)
        # Vol de venda = 30.000,00 (> 20k, tributável).
        # Offset de 1000,00 de prejuízo -> Base de cálculo 21.000,00 -> DARF 3150,00
        op5 = OperacaoB3(
            contribuinte_id=cid,
            data_operacao=date(2024, 4, 15),
            tipo_operacao="venda",
            ticker="VALE3",
            quantidade=Decimal("100"),
            preco_unitario=Decimal("300.00"),
            valor_total=Decimal("30000.00"),
        )
        db.add(op5)

        db.commit()
        print("Dados simulados criados com sucesso.")

        # ── Testar Engine ─────────────────────────────────────────
        print("\n── 2. Teste da Engine B3 ──")
        meses_apurados, prej_final = apurar_meses_b3(cid, 2024, db)

        # Esperamos os meses 2, 3 e 4 processados com vendas. 
        # (Se o mês 1 só tem compras, total_vendas_b3 e lucro = 0. Então ele não reporta prejuízo nem lucro.
        # Vai entrar no result_dicts? Sim, no dict, todo mês com operacao será varrido, se tiver operações)
        # Filtremos por meses com operações de venda geradoras de resultado > 0.
        meses_dict = {m["mes"]: m for m in meses_apurados}

        debug_assert(2 in meses_dict, f"Mês 2 ausente")
        if 2 in meses_dict:
            m2 = meses_dict[2]
            debug_assert(m2["lucro_isento"] == "250.00", f"M2 Lucro Isento Incorreto: {m2['lucro_isento']}")
            debug_assert(m2["lucro_tributavel"] == "0.00", "M2 Lucro Tributavel deveria ser 0")

        debug_assert(3 in meses_dict, f"Mês 3 ausente")
        if 3 in meses_dict:
            m3 = meses_dict[3]
            debug_assert(m3["prejuizo_mes_gerado"] == "1000.00", f"M3 Prejuizo gerado incorreto: {m3['prejuizo_mes_gerado']}")
            debug_assert(m3["prejuizo_a_compensar_seguinte"] == "1000.00", "M3 Carry Over incorreto")

        debug_assert(4 in meses_dict, f"Mês 4 ausente")
        if 4 in meses_dict:
            m4 = meses_dict[4]
            debug_assert(m4["total_vendas"] == "30000.00", f"M4 Total Vendas incorreto: {m4['total_vendas']}")
            debug_assert(m4["prejuizo_acumulado_utilizado"] == "1000.00", "M4 Offset incorreto")
            debug_assert(m4["lucro_tributavel"] == "21000.00", f"M4 Lucro Tributavel incorreto: {m4['lucro_tributavel']}")
            debug_assert(m4["imposto_devido"] == "3150.00", f"M4 DARF devido incorreto: {m4['imposto_devido']}")
            debug_assert(m4["prejuizo_a_compensar_seguinte"] == "0.00", "M4 Carry Over final incorreto")

        debug_assert(prej_final == Decimal("0.00"), "Prejuízo final do ano deveria ter zerado")


        # ── Testar Cripto ─────────────────────────────────────────
        print("\n── 3. Teste da Engine Cripto ──")

        # Mês com isenção
        cripto1 = AtivoCripto(
            contribuinte_id=cid,
            data_operacao=date(2024, 7, 1),
            tipo_operacao="venda",
            moeda="BTC",
            quantidade=Decimal("0.1"),
            preco_unitario_brl=Decimal("150000.00"),
            valor_total_brl=Decimal("15000.00"), # < 35k
        )
        
        # Mês com limite estourado
        cripto2 = AtivoCripto(
            contribuinte_id=cid,
            data_operacao=date(2024, 8, 10),
            tipo_operacao="venda",
            moeda="ETH",
            quantidade=Decimal("10"),
            preco_unitario_brl=Decimal("2000.00"),
            valor_total_brl=Decimal("20000.00"),
        )
        cripto3 = AtivoCripto(
            contribuinte_id=cid,
            data_operacao=date(2024, 8, 15),
            tipo_operacao="venda",
            moeda="SOL",
            quantidade=Decimal("100"),
            preco_unitario_brl=Decimal("200.00"),
            valor_total_brl=Decimal("20000.00"), # Soma = 40.000 no mês 8
        )
        db.add_all([cripto1, cripto2, cripto3])
        db.commit()

        alertas = auditar_cripto_vendas(cid, 2024, db)
        
        debug_assert(len(alertas) == 1, f"Deveria ter 1 alerta, teve {len(alertas)}")
        if alertas:
            al = alertas[0]
            debug_assert(al["ano"] == 2024 and al["mes"] == 8, f"Mês do alerta errado: {al['mes']}")
            debug_assert(al["total_vendas"] == "40000.00", f"Total vendas cripto errado: {al['total_vendas']}")
            debug_assert(al["limite_isencao"] == "35000.00", f"Limite incorreto na config")

    finally:
        db.close()

    print("\n" + "=" * 60)
    if errors:
        print("❌  FINALIZADO COM FALHAS:")
        for e in errors:
            print(f"   • {e}")
        sys.exit(1)
    else:
        print("🎉  TODOS OS TESTES DA FASE 4 PASSARAM!")
        sys.exit(0)


if __name__ == "__main__":
    run_tests()
