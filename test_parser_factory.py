"""
Testes para o ParserFactory — verifica que a fábrica retorna a estratégia
correta com base em texto simulado (sem pdfplumber, sem banco de dados).
"""
import pytest

from app.services.pdf_strategies.factory import ParserFactory
from app.services.pdf_strategies.generic import GenericParserStrategy
from app.services.pdf_strategies.institutions import (
    BradescoParserStrategy,
    ItauParserStrategy,
    NubankParserStrategy,
    XPParserStrategy,
)


# ─── Fixtures de texto simulado ───────────────────────────────────────────────

TEXTO_NUBANK_CNPJ = """
INFORME DE RENDIMENTOS 2024
CNPJ: 18.236.120/0001-58
Razão Social: Nu Pagamentos S.A.
ANO-CALENDÁRIO: 2024
"""

TEXTO_NUBANK_KEYWORD = """
INFORME DE RENDIMENTOS
Nu Invest Corretora de Valores S.A.
ANO-CALENDÁRIO: 2024
"""

TEXTO_ITAU_CNPJ = """
BANCO ITAÚ UNIBANCO S.A.
CNPJ 60.701.190/0001-04
Ano-Calendário 2024
Rendimentos Tributáveis 1.500,00
"""

TEXTO_BRADESCO_CNPJ = """
Banco Bradesco S.A.
CNPJ 60.746.948/0001-12
ANO-CALENDÁRIO 2024
"""

TEXTO_XP_KEYWORD = """
XP Investimentos CCTVM S.A.
Informe de Rendimentos - Ano-Calendário 2024
"""

TEXTO_GENERICO = """
INFORME DE RENDIMENTOS FINANCEIROS
Banco Desconhecido Ltda
CNPJ 99.999.999/0001-00
ANO-CALENDÁRIO: 2024
Rendimentos Sujeitos à Tributação Exclusiva/Definitiva
Rendimentos de CDB         1.234,56
Saldo em 31/12/2023  R$ 10.000,00
Saldo em 31/12/2024  R$ 12.000,00
"""

TEXTO_GENERICO_HOLERITE = """
RENDIMENTOS TRIBUTÁVEIS, DEDUÇÕES E IMPOSTO RETIDO NA FONTE
CNPJ 99.888.777/0001-11
Razão Social: Empresa Qualquer S.A.
ANO-CALENDÁRIO: 2024
3.1 - Total dos rendimentos     72.000,00
3.2 - Contribuição previdenciária  8.800,00
3.5 - Imposto de renda retido na fonte   5.400,00
"""


# ─── Testes de seleção por CNPJ ───────────────────────────────────────────────

def test_factory_seleciona_nubank_por_cnpj():
    strategy = ParserFactory.get_strategy(TEXTO_NUBANK_CNPJ)
    assert isinstance(strategy, NubankParserStrategy)


def test_factory_seleciona_itau_por_cnpj():
    strategy = ParserFactory.get_strategy(TEXTO_ITAU_CNPJ)
    assert isinstance(strategy, ItauParserStrategy)


def test_factory_seleciona_bradesco_por_cnpj():
    strategy = ParserFactory.get_strategy(TEXTO_BRADESCO_CNPJ)
    assert isinstance(strategy, BradescoParserStrategy)


# ─── Testes de seleção por keyword ────────────────────────────────────────────

def test_factory_seleciona_nubank_por_keyword():
    strategy = ParserFactory.get_strategy(TEXTO_NUBANK_KEYWORD)
    assert isinstance(strategy, NubankParserStrategy)


def test_factory_seleciona_xp_por_keyword():
    strategy = ParserFactory.get_strategy(TEXTO_XP_KEYWORD)
    assert isinstance(strategy, XPParserStrategy)


# ─── Fallback genérico ────────────────────────────────────────────────────────

def test_factory_fallback_generico():
    strategy = ParserFactory.get_strategy(TEXTO_GENERICO)
    assert isinstance(strategy, GenericParserStrategy)


# ─── Integração: parse completo com estratégia genérica ──────────────────────

def test_generic_strategy_parse_informe_bancario():
    from app.services.pdf_parser import parse_informe_text
    result = parse_informe_text(TEXTO_GENERICO)

    assert result.tipo_informe == "banco_corretora"
    assert result.ano_calendario == 2024
    assert any(r.valor > 0 for r in result.rendimentos), "Deveria encontrar pelo menos 1 rendimento"
    assert any(s.valor > 0 for s in result.saldos), "Deveria encontrar pelo menos 1 saldo"


def test_generic_strategy_parse_holerite():
    from app.services.pdf_parser import parse_informe_text
    result = parse_informe_text(TEXTO_GENERICO_HOLERITE)

    assert result.tipo_informe == "trabalho_assalariado"
    assert result.rendimento_trabalho is not None
    from decimal import Decimal
    assert result.rendimento_trabalho.rendimento_tributavel == Decimal("72000.00")
    assert result.rendimento_trabalho.contribuicao_previdenciaria == Decimal("8800.00")
    assert result.rendimento_trabalho.irrf == Decimal("5400.00")


# ─── Propriedade: estratégia retorna seu nome ─────────────────────────────────

def test_strategy_nome_instituicao():
    assert NubankParserStrategy().nome_instituicao == "Nubank / Nu Invest"
    assert ItauParserStrategy().nome_instituicao == "Itaú Unibanco"
    assert BradescoParserStrategy().nome_instituicao == "Bradesco"
    assert XPParserStrategy().nome_instituicao == "XP Investimentos"
    assert GenericParserStrategy().nome_instituicao == "Genérico (Fallback)"
