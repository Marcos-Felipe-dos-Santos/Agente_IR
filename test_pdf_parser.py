"""
Teste Fase 3 — Parser de Informe de Rendimentos PDF.

Verifica:
  1. Extração de CNPJ (inclusive com quebras de linha)
  2. Extração de Razão Social
  3. Extração de Ano-Calendário
  4. Rendimentos Tributação Exclusiva
  5. Rendimentos Isentos
  6. Saldos em 31/12 (anterior e atual)
  7. Conversão monetária BR → Decimal
  8. Persistência no banco (RendimentoInforme + ContaBancaria)
  9. Resiliência a quebras de linha inesperadas de PDF
"""

import sys
from datetime import date
from decimal import Decimal

from app.core.database import init_db, SessionLocal
from app.models.entities import ContaBancaria, Contribuinte, RendimentoInforme
from app.services.pdf_parser import (
    _extract_cnpj,
    _extract_razao_social,
    _extract_ano,
    _parse_br_money,
    _extract_saldos,
    _extract_rendimentos_from_section,
    parse_informe_text,
    _persist_rendimentos,
    _persist_saldos,
)
from sqlalchemy import delete, select

print("=" * 60)
print("  TESTE FASE 3 — Parser de Informe de Rendimentos PDF")
print("=" * 60)

errors: list[str] = []
init_db()


# ═══════════════════════════════════════════════════════════════════
#  1. Testes unitários: _parse_br_money
# ═══════════════════════════════════════════════════════════════════
print("\n── 1. Testes unitários: _parse_br_money ──")
money_tests = [
    ("R$ 1.500,00", Decimal("1500.00")),
    ("1.234,56", Decimal("1234.56")),
    ("R$28,50", Decimal("28.50")),
    ("15.000,00", Decimal("15000.00")),
    ("567,89", Decimal("567.89")),
    ("0,00", Decimal("0.00")),
    ("R$ 2.345,67", Decimal("2345.67")),
    ("-R$ 100,00", Decimal("-100.00")),
    ("18.500,00", Decimal("18500.00")),
    ("", None),
    ("-", None),
]
for raw_val, expected in money_tests:
    result = _parse_br_money(raw_val)
    if result != expected:
        errors.append(f"_parse_br_money('{raw_val}') = {result}, esperado {expected}")
        print(f"  ❌ '{raw_val}' → {result} (esperado {expected})")
    else:
        print(f"  ✅ '{raw_val}' → {result}")


# ═══════════════════════════════════════════════════════════════════
#  2. Testes unitários: extração de CNPJ
# ═══════════════════════════════════════════════════════════════════
print("\n── 2. Testes unitários: _extract_cnpj ──")

cnpj_tests = [
    # Formato limpo
    ("CNPJ: 00.000.000/0001-91", "00.000.000/0001-91"),
    # Com CNPJ/MF
    ("CNPJ/MF: 33.592.510/0001-54", "33.592.510/0001-54"),
    # Com quebra de linha no meio (típico de PDF)
    ("CNPJ:\n00.000.000/0001-91", "00.000.000/0001-91"),
    # Com espaços extras
    ("CNPJ :  33.592.510/0001-54", "33.592.510/0001-54"),
    # Sem CNPJ
    ("Documento sem CNPJ aqui", None),
]
for text, expected in cnpj_tests:
    result = _extract_cnpj(text)
    if result != expected:
        errors.append(f"_extract_cnpj: '{text[:40]}...' = {result}, esperado {expected}")
        print(f"  ❌ '{text[:40]}' → {result} (esperado {expected})")
    else:
        print(f"  ✅ CNPJ extraído: {result}")


# ═══════════════════════════════════════════════════════════════════
#  3. Testes unitários: extração de Razão Social
# ═══════════════════════════════════════════════════════════════════
print("\n── 3. Testes unitários: _extract_razao_social ──")

razao_tests = [
    ("RAZÃO SOCIAL: BANCO DO BRASIL S.A.\nCNPJ", "BANCO DO BRASIL S.A"),
    ("NOME EMPRESARIAL: XP INVESTIMENTOS CCTVM S.A.\nOutra coisa", "XP INVESTIMENTOS CCTVM S.A"),
    ("FONTE PAGADORA: ITAÚ UNIBANCO S.A.\n", "ITAÚ UNIBANCO S.A"),
    # Sem razão social
    ("Texto sem razao social", None),
]
for text, expected in razao_tests:
    result = _extract_razao_social(text)
    if result != expected:
        errors.append(f"_extract_razao_social: '{text[:40]}...' = {result}, esperado {expected}")
        print(f"  ❌ '{text[:40]}' → {result} (esperado {expected})")
    else:
        print(f"  ✅ Razão Social: {result}")


# ═══════════════════════════════════════════════════════════════════
#  4. Testes unitários: extração de Ano-Calendário
# ═══════════════════════════════════════════════════════════════════
print("\n── 4. Testes unitários: _extract_ano ──")

ano_tests = [
    ("ANO-CALENDÁRIO DE 2024", 2024),
    ("ANO CALENDARIO: 2025", 2025),
    ("ANO-CALENDÁRIO DE  2024", 2024),
    # Com quebra de linha
    ("ANO-CALENDÁRIO\nDE 2024", 2024),
    ("Sem ano aqui", None),
]
for text, expected in ano_tests:
    result = _extract_ano(text)
    if result != expected:
        errors.append(f"_extract_ano: '{text[:40]}' = {result}, esperado {expected}")
        print(f"  ❌ '{text[:40]}' → {result} (esperado {expected})")
    else:
        print(f"  ✅ Ano: {result}")


# ═══════════════════════════════════════════════════════════════════
#  5. Testes unitários: extração de rendimentos de seção
# ═══════════════════════════════════════════════════════════════════
print("\n── 5. Testes unitários: rendimentos de seção ──")

# Seção típica de rendimentos
section_text_clean = """
Tipo de Rendimento                                    Valor (R$)
Rendimentos de operações financeiras (CDB, RDB)       1.234,56
Rendimentos de Fundos de Investimento                   890,00
"""

rends = _extract_rendimentos_from_section(section_text_clean, "tributacao_exclusiva")
if len(rends) != 2:
    errors.append(f"Esperado 2 rendimentos na seção limpa, obteve {len(rends)}")
    print(f"  ❌ Seção limpa: {len(rends)} rendimentos (esperado 2)")
else:
    print(f"  ✅ Seção limpa: {len(rends)} rendimentos extraídos")
    for r in rends:
        print(f"     → {r.descricao}: R$ {r.valor}")

# Seção com quebras de linha e espaços extras (típico de PDF)
section_text_broken = """
Tipo de Rendimento    Valor (R$)
Rendimentos de caderneta de                            567,89
poupança
LCI - Letra de Crédito    2.345,67
Imobiliário
LCA - Letra de Crédito do Agronegócio     450,00
"""

rends_broken = _extract_rendimentos_from_section(section_text_broken, "isento")
if len(rends_broken) < 2:
    # Pelo menos LCI e LCA devem ser extraídos (poupança pode quebrar)
    errors.append(f"Esperado ao menos 2 rendimentos na seção quebrada, obteve {len(rends_broken)}")
    print(f"  ❌ Seção quebrada: {len(rends_broken)} rendimentos (esperado ≥2)")
else:
    print(f"  ✅ Seção quebrada: {len(rends_broken)} rendimentos extraídos")
    for r in rends_broken:
        print(f"     → {r.descricao}: R$ {r.valor}")


# ═══════════════════════════════════════════════════════════════════
#  6. Testes unitários: extração de saldos
# ═══════════════════════════════════════════════════════════════════
print("\n── 6. Testes unitários: saldos ──")

saldo_text = """
Conta Corrente
Saldo em 31/12/2023: R$ 15.000,00
Saldo em 31/12/2024: R$ 18.500,00

Poupança
Saldo em 31/12/2023: 5.000,00
Saldo em 31/12/2024: 5.567,89
"""

saldos = _extract_saldos(saldo_text)
if len(saldos) < 4:
    errors.append(f"Esperado 4 saldos, obteve {len(saldos)}")
    print(f"  ❌ Saldos: {len(saldos)} (esperado 4)")
else:
    print(f"  ✅ {len(saldos)} saldos extraídos:")
    for s in saldos:
        print(f"     → {s.tipo_conta} | 31/12/{s.ano} | R$ {s.valor}")

# Verifica tipos de conta detectados
tipos_encontrados = {s.tipo_conta for s in saldos}
if "corrente" not in tipos_encontrados:
    errors.append("Tipo 'corrente' não detectado nos saldos")
    print("  ❌ Tipo 'corrente' não detectado")
else:
    print("  ✅ Tipo 'corrente' detectado")

if "poupanca" not in tipos_encontrados:
    errors.append("Tipo 'poupanca' não detectado nos saldos")
    print("  ❌ Tipo 'poupanca' não detectado")
else:
    print("  ✅ Tipo 'poupanca' detectado")


# ═══════════════════════════════════════════════════════════════════
#  7. Teste de integração: parse_informe_text completo
# ═══════════════════════════════════════════════════════════════════
print("\n── 7. Teste de integração: parse_informe_text ──")

# Simula texto completo de um informe de rendimentos
MOCK_INFORME_TEXT = """
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

informe = parse_informe_text(MOCK_INFORME_TEXT)

# Verificações
if informe.cnpj_fonte != "00.000.000/0001-91":
    errors.append(f"CNPJ incorreto: {informe.cnpj_fonte}")
    print(f"  ❌ CNPJ: {informe.cnpj_fonte}")
else:
    print(f"  ✅ CNPJ: {informe.cnpj_fonte}")

if informe.razao_social != "BANCO DO BRASIL S.A":
    errors.append(f"Razão Social incorreta: {informe.razao_social}")
    print(f"  ❌ Razão Social: {informe.razao_social}")
else:
    print(f"  ✅ Razão Social: {informe.razao_social}")

if informe.ano_calendario != 2024:
    errors.append(f"Ano incorreto: {informe.ano_calendario}")
    print(f"  ❌ Ano: {informe.ano_calendario}")
else:
    print(f"  ✅ Ano: {informe.ano_calendario}")

print(f"\n  📊 Rendimentos encontrados: {len(informe.rendimentos)}")
for r in informe.rendimentos:
    print(f"     [{r.categoria}] {r.descricao}: R$ {r.valor}")

print(f"\n  📊 Saldos encontrados: {len(informe.saldos)}")
for s in informe.saldos:
    print(f"     {s.tipo_conta} | 31/12/{s.ano} | R$ {s.valor}")

# Deve ter ao menos 2 rendimentos tributação exclusiva
trib_excl = [r for r in informe.rendimentos if r.categoria == "tributacao_exclusiva"]
if len(trib_excl) < 2:
    errors.append(f"Esperado ≥2 rendimentos tributação exclusiva, obteve {len(trib_excl)}")
    print(f"  ❌ Tribut. exclusiva: {len(trib_excl)} (esperado ≥2)")
else:
    print(f"  ✅ Tribut. exclusiva: {len(trib_excl)} rendimentos")

# Deve ter ao menos 2 rendimentos isentos
isentos = [r for r in informe.rendimentos if r.categoria == "isento"]
if len(isentos) < 2:
    errors.append(f"Esperado ≥2 rendimentos isentos, obteve {len(isentos)}")
    print(f"  ❌ Isentos: {len(isentos)} (esperado ≥2)")
else:
    print(f"  ✅ Isentos: {len(isentos)} rendimentos")

# Deve ter ao menos 2 saldos
if len(informe.saldos) < 2:
    errors.append(f"Esperado ≥2 saldos, obteve {len(informe.saldos)}")
else:
    print(f"  ✅ Saldos: {len(informe.saldos)} encontrados")


# ═══════════════════════════════════════════════════════════════════
#  8. Teste de resiliência: quebras de linha inesperadas
# ═══════════════════════════════════════════════════════════════════
print("\n── 8. Teste de resiliência: quebras de linha de PDF ──")

# Texto com quebras agressivas típicas de PDF mal formatado
BROKEN_INFORME = """INFORME DE RENDIMENTOS
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

broken_result = parse_informe_text(BROKEN_INFORME)

if broken_result.cnpj_fonte != "33.592.510/0001-54":
    errors.append(f"CNPJ quebrado não extraído: {broken_result.cnpj_fonte}")
    print(f"  ❌ CNPJ com quebra: {broken_result.cnpj_fonte}")
else:
    print(f"  ✅ CNPJ com quebra de linha: {broken_result.cnpj_fonte}")

if broken_result.ano_calendario != 2024:
    errors.append(f"Ano com quebra não extraído: {broken_result.ano_calendario}")
    print(f"  ❌ Ano com quebra: {broken_result.ano_calendario}")
else:
    print(f"  ✅ Ano com quebra de linha: {broken_result.ano_calendario}")

if broken_result.razao_social:
    print(f"  ✅ Razão Social com quebra: {broken_result.razao_social}")
else:
    errors.append("Razão Social com quebra não extraída")
    print(f"  ❌ Razão Social com quebra: None")

broken_rends = len(broken_result.rendimentos)
if broken_rends >= 2:
    print(f"  ✅ {broken_rends} rendimentos extraídos de texto quebrado")
    for r in broken_result.rendimentos:
        print(f"     → [{r.categoria}] {r.descricao}: R$ {r.valor}")
else:
    errors.append(f"Texto quebrado: esperado ≥2 rendimentos, obteve {broken_rends}")
    print(f"  ❌ {broken_rends} rendimentos (esperado ≥2)")

broken_saldos = len(broken_result.saldos)
if broken_saldos >= 2:
    print(f"  ✅ {broken_saldos} saldos extraídos de texto quebrado")
else:
    errors.append(f"Texto quebrado: esperado ≥2 saldos, obteve {broken_saldos}")
    print(f"  ❌ {broken_saldos} saldos (esperado ≥2)")


# ═══════════════════════════════════════════════════════════════════
#  9. Teste de persistência no banco
# ═══════════════════════════════════════════════════════════════════
print("\n── 9. Teste de persistência no banco ──")

db = SessionLocal()
try:
    # Limpa dados anteriores
    db.execute(delete(RendimentoInforme))
    db.execute(delete(ContaBancaria))
    db.execute(delete(Contribuinte))
    db.commit()

    # Cria contribuinte
    contrib = Contribuinte(
        cpf="888.888.888-88",
        nome_completo="Teste PDF Parser",
        data_nascimento=date(1985, 3, 20),
        ano_exercicio=2025,
    )
    db.add(contrib)
    db.commit()
    db.refresh(contrib)
    print(f"  ✅ Contribuinte de teste criado (id={contrib.id})")

    # Persiste rendimentos do informe limpo
    informe_limpo = parse_informe_text(MOCK_INFORME_TEXT)
    rends_inseridos = _persist_rendimentos(informe_limpo, contrib.id, db)
    db.commit()

    # Verifica rendimentos no banco
    rends_db = list(db.scalars(
        select(RendimentoInforme).where(RendimentoInforme.contribuinte_id == contrib.id)
    ).all())
    print(f"  ✅ {len(rends_db)} rendimentos persistidos no banco")
    for r in rends_db:
        print(f"     → [{r.categoria}] {r.descricao}: R$ {r.valor}")

    if len(rends_db) != rends_inseridos:
        errors.append(f"Rendimentos: {len(rends_db)} no banco ≠ {rends_inseridos} informados")

    # Persiste saldos
    saldos_atualizados = _persist_saldos(informe_limpo, contrib.id, db)
    db.commit()

    # Verifica contas no banco
    contas_db = list(db.scalars(
        select(ContaBancaria).where(ContaBancaria.contribuinte_id == contrib.id)
    ).all())
    print(f"  ✅ {len(contas_db)} contas bancárias criadas/atualizadas")
    for c in contas_db:
        print(
            f"     → {c.instituicao} ({c.tipo_conta}): "
            f"31/12 ant=R${c.saldo_31_12_anterior} | 31/12 atu=R${c.saldo_31_12_atual}"
        )

    # Verifica se saldo corrente está correto
    corrente = next((c for c in contas_db if c.tipo_conta == "corrente"), None)
    if corrente:
        if corrente.saldo_31_12_anterior == Decimal("15000.00"):
            print(f"  ✅ Saldo anterior corrente: R$ {corrente.saldo_31_12_anterior}")
        else:
            errors.append(f"Saldo anterior corrente: {corrente.saldo_31_12_anterior} ≠ 15000.00")
            print(f"  ❌ Saldo anterior corrente: R$ {corrente.saldo_31_12_anterior}")

        if corrente.saldo_31_12_atual == Decimal("18500.00"):
            print(f"  ✅ Saldo atual corrente: R$ {corrente.saldo_31_12_atual}")
        else:
            errors.append(f"Saldo atual corrente: {corrente.saldo_31_12_atual} ≠ 18500.00")
            print(f"  ❌ Saldo atual corrente: R$ {corrente.saldo_31_12_atual}")
    else:
        errors.append("Conta corrente não encontrada no banco")
        print("  ❌ Conta corrente não encontrada")

finally:
    db.close()


# ═══════════════════════════════════════════════════════════════════
#  Resultado final
# ═══════════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
if errors:
    print("❌  FALHAS ENCONTRADAS:")
    for e in errors:
        print(f"   • {e}")
    sys.exit(1)
else:
    print("🎉  TODOS OS TESTES DA FASE 3 PASSARAM!")
    sys.exit(0)
