"""
Testes de Regex — Extração de despesas médicas via parse_informe_text.

Valida que a regex captura corretamente CNPJ e valor de despesas médicas
em texto simulado de holerite.
"""
import pytest
from decimal import Decimal

from app.services.pdf_parser import parse_informe_text


MOCK_HOLERITE = """
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


def test_cabecalho_holerite():
    result = parse_informe_text(MOCK_HOLERITE)
    assert result.cnpj_fonte == "11.222.333/0001-99"
    assert result.ano_calendario == 2024


def test_despesas_medicas_extraidas():
    result = parse_informe_text(MOCK_HOLERITE)
    assert len(result.despesas_medicas) >= 2, (
        f"Esperava ao menos 2 despesas médicas, encontrou {len(result.despesas_medicas)}"
    )


def test_despesa_unimed():
    result = parse_informe_text(MOCK_HOLERITE)
    unimed = next(
        (d for d in result.despesas_medicas if "44.555.666/0001-22" in d.cnpj_prestador),
        None,
    )
    assert unimed is not None, "Despesa Unimed não encontrada"
    assert unimed.cnpj_prestador == "44.555.666/0001-22"
    assert Decimal(str(unimed.valor_pago)) == Decimal("5900.50")


def test_despesa_odontoprev():
    result = parse_informe_text(MOCK_HOLERITE)
    odonto = next(
        (d for d in result.despesas_medicas if "77.888.999/0001-33" in d.cnpj_prestador),
        None,
    )
    assert odonto is not None, "Despesa OdontoPrev não encontrada"
    assert odonto.cnpj_prestador == "77.888.999/0001-33"
    assert Decimal(str(odonto.valor_pago)) == Decimal("1200.80")
