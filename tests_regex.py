"""
Testes de Regex — Extração de despesas médicas via parse_informe_text.
"""
from app.services.pdf_parser import parse_informe_text

mock_text = """
COMPROVANTE DE RENDIMENTOS PAGOS E DE IMPOSTO SOBRE A RENDA RETIDO NA FONTE
ANO-CALENDÁRIO DE 2024
1. FONTES PAGADORAS
CNPJ: 11.222.333/0001-99
Nome Empresarial: Empresa Trabalhadora S.A.
3. RENDIMENTOS TRIBUTÁVEIS, DEDUÇÕES E IMPOSTO RETIDO NA FONTE
3.1 - Total dos rendimentos (inclusive férias) 120.000,50
3.2 - Contribuição previdenciária oficial      12.000,00
3.5 - Imposto de renda retido na fonte         20.500,75
7. INFORMAÇÕES COMPLEMENTARES
Despesas Médicas Unimed Seguros Saúde CNPJ: 44.555.666/0001-22  R$ 5.900,50
Outras despesas OdontoPrev CNPJ 77.888.999/0001-33 pagas com valor de R$ 1.200,80
"""

result = parse_informe_text(mock_text)
print("Despesas:")
for d in result.despesas_medicas:
    print(f" - CNPJ: {d.cnpj_prestador} | Valor: {d.valor_pago}")

assert result.cnpj_fonte == "11.222.333/0001-99", f"CNPJ incorreto: {result.cnpj_fonte}"
assert result.ano_calendario == 2024, f"Ano incorreto: {result.ano_calendario}"
assert len(result.despesas_medicas) == 2, f"Esperado 2 despesas, obteve {len(result.despesas_medicas)}"
assert result.despesas_medicas[0].valor_pago is not None, "Valor da primeira despesa é None"
print("✅ Todos os asserts de regex passaram.")
