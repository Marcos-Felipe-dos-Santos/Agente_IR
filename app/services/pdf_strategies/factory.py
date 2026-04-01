"""
ParserFactory — Fábrica de Estratégias de PDF.

Analisa o texto inicial do PDF e decide qual BankParserStrategy instanciar
com base em CNPJs conhecidos ou keywords de nome de banco.

Para registrar um novo banco:
    1. Crie a estratégia em institutions.py.
    2. Adicione-a à lista _REGISTRY abaixo.
"""
from __future__ import annotations

import re
import logging

from app.services.pdf_strategies.base import BankParserStrategy
from app.services.pdf_strategies.generic import GenericParserStrategy
from app.services.pdf_strategies.institutions import (
    BradescoParserStrategy,
    ItauParserStrategy,
    NubankParserStrategy,
    XPParserStrategy,
)

logger = logging.getLogger(__name__)

# Estratégias registradas em ordem de prioridade (mais específicas primeiro).
# A GenericParserStrategy NÃO deve estar aqui — é sempre o fallback final.
_REGISTRY: list[type[BankParserStrategy]] = [
    NubankParserStrategy,
    ItauParserStrategy,
    BradescoParserStrategy,
    XPParserStrategy,
]

_CNPJ_DIGITS_RE = re.compile(r"\d{2}[\s.]*\d{3}[\s.]*\d{3}[\s/]*\d{4}[\s-]*\d{2}")


def _extract_cnpj_digits_set(text: str) -> set[str]:
    """Extrai todos os CNPJs do texto como strings de 14 dígitos puros."""
    return {
        re.sub(r"[^\d]", "", m.group())
        for m in _CNPJ_DIGITS_RE.finditer(text[:3000])  # só analisa início do doc
    }


def _normalize_text_lower(text: str) -> str:
    """Retorna os primeiros 3000 chars em lowercase para keyword matching."""
    return text[:3000].lower()


class ParserFactory:
    """
    Determina dinamicamente qual estratégia usar para um dado PDF.

    Algoritmo de decisão:
        1. Extrai CNPJs do texto inicial → compara com CNPJS_CONHECIDOS de cada estratégia.
        2. Se não encontrar CNPJ, procura KEYWORDS no texto normalizado.
        3. Se nenhuma estratégia específica corresponder → retorna GenericParserStrategy.
    """

    @staticmethod
    def get_strategy(text: str) -> BankParserStrategy:
        """
        Retorna a instância da estratégia adequada para o texto do PDF.

        Args:
            text: Texto completo (ou parcial) extraído do PDF.

        Returns:
            Instância de BankParserStrategy pronta para uso.
        """
        cnpjs_no_doc = _extract_cnpj_digits_set(text)
        text_lower = _normalize_text_lower(text)

        for StrategyClass in _REGISTRY:
            # Prioridade 1: Match por CNPJ (determinístico)
            known_cnpjs: set[str] = getattr(StrategyClass, "CNPJS_CONHECIDOS", set())
            if cnpjs_no_doc & known_cnpjs:
                logger.info(
                    "ParserFactory: Estratégia '%s' selecionada por CNPJ.",
                    StrategyClass.__name__,
                )
                return StrategyClass()

            # Prioridade 2: Match por keyword no texto inicial
            keywords: set[str] = getattr(StrategyClass, "KEYWORDS", set())
            if any(kw in text_lower for kw in keywords):
                logger.info(
                    "ParserFactory: Estratégia '%s' selecionada por keyword.",
                    StrategyClass.__name__,
                )
                return StrategyClass()

        logger.info("ParserFactory: Nenhuma estratégia específica encontrada. Usando GenericParserStrategy.")
        return GenericParserStrategy()
