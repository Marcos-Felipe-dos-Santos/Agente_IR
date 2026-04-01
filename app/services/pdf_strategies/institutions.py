"""
Estratégias específicas por instituição bancária.

Cada classe é um 'skeleton' pronto para extensão — o método `nome_instituicao`
e os CNPJs/keywords de detecção já estão definidos. A lógica de extração,
por enquanto, herda do GenericParserStrategy e pode ser sobrescrita
quando tiver o layout real de cada banco disponível para análise.

Para ADICIONAR SUPORTE A UM NOVO BANCO:
    1. Crie uma nova classe aqui herdando de GenericParserStrategy
       (ou BankParserStrategy se preferir partir do zero).
    2. Defina seus `CNPJS_CONHECIDOS` e `KEYWORDS`.
    3. Sobrescreva os métodos cujo layout difere do padrão genérico.
    4. Registre a classe no ParserFactory (factory.py).
"""
from __future__ import annotations

from decimal import Decimal

from app.services.pdf_strategies.generic import GenericParserStrategy
from app.services.pdf_strategies.base import (
    RendimentoExtraido,
    SaldoExtraido,
    RendimentoTrabalhoExtraido,
)


# ─── Nubank ───────────────────────────────────────────────────────────────────

class NubankParserStrategy(GenericParserStrategy):
    """
    Estratégia para informes do Nubank / Nu Invest.

    Layouts conhecidos: Informe de Rendimentos NuInvest (Nu Corretora).
    CNPJ principal: 18.236.120/0001-58 (Nubank S.A.)
    """

    CNPJS_CONHECIDOS = {"18236120000158"}
    KEYWORDS = {"nubank", "nu invest", "nuconta", "nu corretora"}

    @property
    def nome_instituicao(self) -> str:
        return "Nubank / Nu Invest"

    # TODO: Sobrescrever extract_rendimentos quando tivermos
    # um PDF real do Nubank para analisar o layout.
    # O layout Nubank 2024 usa colunas separadas com TAB, o que
    # exigirá tratamento específico de alinhamento horizontal.


# ─── Itaú ─────────────────────────────────────────────────────────────────────

class ItauParserStrategy(GenericParserStrategy):
    """
    Estratégia para informes do Itaú Unibanco.

    Layouts conhecidos: Informe de Rendimentos Itaú Pessoa Física.
    CNPJ principal: 60.701.190/0001-04 (Itaú Unibanco S.A.)
    """

    CNPJS_CONHECIDOS = {"60701190000104"}
    KEYWORDS = {"itaú", "itau", "itaú unibanco"}

    @property
    def nome_instituicao(self) -> str:
        return "Itaú Unibanco"

    # TODO: O Itaú usa um cabeçalho próprio com "BANCO ITAÚ S.A." e
    # organiza os rendimentos em tabelas com bordas. A seção de saldos
    # aparece antes dos rendimentos (ordem invertida vs layout genérico).
    # Sobrescrever extract_saldos quando tivermos PDF real.


# ─── Bradesco ─────────────────────────────────────────────────────────────────

class BradescoParserStrategy(GenericParserStrategy):
    """
    Estratégia para informes do Bradesco / Bradesco Corretora.

    Layouts conhecidos: Informe de Rendimentos BBI (Banco Bradesco BBI).
    CNPJ principal: 60.746.948/0001-12 (Banco Bradesco S.A.)
    """

    CNPJS_CONHECIDOS = {"60746948000112"}
    KEYWORDS = {"bradesco", "bradesco corretora", "bradesco bbi"}

    @property
    def nome_instituicao(self) -> str:
        return "Bradesco"

    # TODO: O Bradesco usa fonte proprietária e quebras de linha agressivas
    # entre o código do rendimento e o valor. Regex especial necessária.


# ─── XP Investimentos ─────────────────────────────────────────────────────────

class XPParserStrategy(GenericParserStrategy):
    """
    Estratégia para informes da XP Investimentos / XP Corretora.

    CNPJ principal: 02.332.886/0001-04 (XP Investimentos CCTVM S.A.)
    """

    CNPJS_CONHECIDOS = {"02332886000104"}
    KEYWORDS = {"xp investimentos", "xp inc", "xp corretora"}

    @property
    def nome_instituicao(self) -> str:
        return "XP Investimentos"
