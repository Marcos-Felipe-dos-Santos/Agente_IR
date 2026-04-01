"""
Estratégia Genérica de Fallback.

Encapsula toda a lógica Regex original do pdf_parser.py.
É usada quando nenhuma estratégia específica de banco é identificada
pela ParserFactory.
"""
from __future__ import annotations

import re
import unicodedata
from decimal import Decimal, ROUND_HALF_UP

from app.services.pdf_strategies.base import (
    BankParserStrategy,
    DespesaMedicaExtraido,
    RendimentoExtraido,
    RendimentoTrabalhoExtraido,
    SaldoExtraido,
)

TWO_PLACES = Decimal("0.01")

# ─── Helpers ──────────────────────────────────────────────────────────────────

def _clean_value_str(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    s = re.sub(r"[\u00a0\u2007\u202f\u2009]", " ", s)
    return s.strip()


def _parse_br_money(value: str) -> Decimal | None:
    s = _clean_value_str(value)
    if not s or s == "-":
        return None
    negative = s.startswith("-") or "- " in s
    s = re.sub(r"^[\s\-]*R?\$?\s*", "", s, flags=re.IGNORECASE).strip()
    s = s.lstrip("-").strip()
    if not s:
        return None
    if "," in s:
        s = s.replace(".", "")
        s = s.replace(",", ".")
    try:
        result = Decimal(s).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
        return -result if negative else result
    except Exception:
        return None


# ─── Regex Patterns (movidos do pdf_parser.py original) ───────────────────────

_CNPJ_PATTERN = re.compile(
    r"CNPJ[\s/MF:]*[\s:]*"
    r"(\d{2}[\s.]*\d{3}[\s.]*\d{3}[\s/]*\d{4}[\s-]*\d{2})",
    re.IGNORECASE,
)
_ANO_PATTERN = re.compile(
    r"ANO[\s-]*CALEND[ÁA]RIO[\s:DE]*(\d{4})",
    re.IGNORECASE,
)
_RAZAO_PATTERNS = [
    re.compile(r"(?:RAZ[ÃA]O\s*SOCIAL|NOME\s*EMPRESARIAL)[\s:]*(.+?)(?:\n|CNPJ|$)", re.IGNORECASE),
    re.compile(r"FONTE\s*PAGADORA[\s:]*(.+?)(?:\n|CNPJ|$)", re.IGNORECASE),
]
_SECTION_TRIB_EXCLUSIVA = re.compile(
    r"(?:3\.?\s*[-–]?\s*)?RENDIMENTOS?\s+SUJEITOS?\s+[ÀA]\s+TRIBUTA[ÇC][ÃA]O\s+"
    r"EXCLUSIVA[\s/]*DEFINITIVA",
    re.IGNORECASE,
)
_SECTION_ISENTOS = re.compile(
    r"(?:4\.?\s*[-–]?\s*)?RENDIMENTOS?\s+ISENTOS?\s+E\s+N[ÃA]O\s+TRIBUT[ÁA]VEIS?",
    re.IGNORECASE,
)
_SECTION_TRIBUTAVEL = re.compile(
    r"(?:1\.?\s*[-–]?\s*)?RENDIMENTOS?\s+TRIBUT[ÁA]VEIS?",
    re.IGNORECASE,
)
_NEXT_SECTION = re.compile(
    r"^\s*\d+\.?\s*[-–]?\s*(?:RENDIMENTO|INFORMA[ÇC]|RELA[ÇC]|IMPOSTO|TOTAL|RESPONSÁVEL)",
    re.IGNORECASE | re.MULTILINE,
)
_VALUE_LINE_PATTERN = re.compile(
    r"^(.+?)\s+"
    r"(R?\$?\s*[\d.,]+(?:,\d{2}))"
    r"\s*$",
    re.MULTILINE,
)
_SALDO_PATTERN = re.compile(
    r"(?:SALDO[\s]*(?:EM|:)?\s*)?"
    r"31[\s/]*12[\s/]*(\d{4})"
    r"[\s:]*R?\$?\s*([\d.,]+(?:,\d{2}))",
    re.IGNORECASE,
)
_TIPO_CONTA_PATTERN = re.compile(
    r"(CONTA\s+CORRENTE|POUPAN[ÇC]A|CDB|RDB|LCI|LCA|FUNDO|"
    r"APLICA[ÇC][ÃA]O|INVESTIMENTO|TESOURO|RENDA\s+FIXA|"
    r"A[ÇC][ÕO]ES|FII|CORRETORA)",
    re.IGNORECASE,
)

# Holerite patterns
_SECTION_HOLERITE = re.compile(
    r"RENDIMENTOS\s+TRIBUT[ÁA]VEIS[(,\s]*DEDU[ÇC][ÕO]ES\s+E\s+IMPOSTO\s+RETIDO\s+NA\s+FONTE",
    re.IGNORECASE,
)
_SALARIO_PATTERN = re.compile(
    r"3\.1[\s\.\-]*Total dos rendimentos[^\n]{0,40}?"
    r"(?:R?\$?\s*(?:[\d.,]+(?:,\d{2}))\s*)?"
    r"R?\$?\s*([\d.]+(?:,\d{2}))",
    re.IGNORECASE,
)
_INSS_PATTERN = re.compile(
    r"3\.2[\s\.\-]*Contribui[çc][ãa]o previdenci[áa]ria[^\n]{0,40}?"
    r"(?:R?\$?\s*(?:[\d.,]+(?:,\d{2}))\s*)?"
    r"R?\$?\s*([\d.]+(?:,\d{2}))",
    re.IGNORECASE,
)
_IRRF_HOLERITE_PATTERN = re.compile(
    r"3\.5[\s\.\-]*Imposto(?: de renda)? retido na fonte[^\n]{0,40}?"
    r"(?:R?\$?\s*(?:[\d.,]+(?:,\d{2}))\s*)?"
    r"R?\$?\s*([\d.]+(?:,\d{2}))",
    re.IGNORECASE,
)
_SAUDE_GULOSA_PATTERN = re.compile(
    r"(?:sa[úu]de|m[ée]dic[a-z]{1,4}|unimed|bradesco|amil|odont[a-z]{0,4}|hospital|cl[íi]nica)"
    r"[^\n]{0,100}?"
    r"(?P<cnpj>\d{2}[\s.]*\d{3}[\s.]*\d{3}[\s/]*\d{4}[\s-]*\d{2})"
    r"[^\n]{0,80}?"
    r"R?\$?\s*(?P<valor>[\d.]+(?:,\d{2}))",
    re.IGNORECASE,
)


# ─── Helpers de Extração ──────────────────────────────────────────────────────

def _find_section_text(text: str, pattern: re.Pattern) -> str | None:
    match = pattern.search(text)
    if not match:
        return None
    start = match.end()
    remaining = text[start:]
    end_match = _NEXT_SECTION.search(remaining)
    return (remaining[: end_match.start()] if end_match else remaining).strip()


def _extract_rendimentos_from_section(section_text: str, categoria: str) -> list[RendimentoExtraido]:
    rendimentos: list[RendimentoExtraido] = []
    cleaned = re.sub(r"\.{3,}", " ", section_text)
    cleaned = re.sub(r"-{3,}", " ", cleaned)
    cleaned = re.sub(r"_{3,}", " ", cleaned)
    cleaned = re.sub(r"[ \t]{2,}", "  ", cleaned)

    for match in _VALUE_LINE_PATTERN.finditer(cleaned):
        desc = match.group(1).strip()
        raw_valor = match.group(2)
        desc_lower = desc.lower()
        if any(kw in desc_lower for kw in ["tipo de rendimento", "discriminação", "valor (r$)", "descrição", "valor r$", "código"]):
            continue
        valor = _parse_br_money(raw_valor)
        if valor and valor > 0:
            desc = re.sub(r"^\d{1,3}\s+", "", desc).strip()
            rendimentos.append(RendimentoExtraido(categoria=categoria, descricao=desc, valor=valor))

    if not rendimentos:
        for line in cleaned.split("\n"):
            m = re.search(r"(R?\$?\s*[\d.]+,\d{2})\s*$", line.strip())
            if m:
                desc = re.sub(r"^\d{1,3}\s+", "", line[: m.start()].strip()).strip()
                valor = _parse_br_money(m.group(1))
                if desc and valor and valor > 0 and not any(kw in desc.lower() for kw in ["tipo de rendimento", "valor (r$)", "valor r$"]):
                    rendimentos.append(RendimentoExtraido(categoria=categoria, descricao=desc, valor=valor))

    return rendimentos


def _extract_cnpj_raw(text: str) -> str | None:
    match = _CNPJ_PATTERN.search(text)
    if not match:
        return None
    digits = re.sub(r"[^\d]", "", match.group(1))
    if len(digits) != 14:
        return None
    return f"{digits[:2]}.{digits[2:5]}.{digits[5:8]}/{digits[8:12]}-{digits[12:14]}"


def _extract_razao_social_raw(text: str) -> str | None:
    for pat in _RAZAO_PATTERNS:
        for m in pat.finditer(text):
            raw = m.group(1).strip()
            if "CNPJ" in raw.upper() or re.match(r"^[\d.\-/:\s]+$", raw):
                continue
            raw = re.sub(r"\s+", " ", raw).strip().rstrip(".")
            if len(raw) > 2:
                return raw
    return None


# ─── Estratégia Genérica ──────────────────────────────────────────────────────

class GenericParserStrategy(BankParserStrategy):
    """
    Estratégia de fallback que usa os Regex genéricos originais.
    Funciona para layouts com a estrutura padrão IRPF (DIRF/Informe de Rendimentos).
    """

    @property
    def nome_instituicao(self) -> str:
        return "Genérico (Fallback)"

    def extract_cabecalho(self, text: str) -> tuple[str | None, str | None, int | None]:
        cnpj = _extract_cnpj_raw(text)
        razao = _extract_razao_social_raw(text)
        ano_match = _ANO_PATTERN.search(text)
        ano = int(ano_match.group(1)) if ano_match and 2020 <= int(ano_match.group(1)) <= 2030 else None
        return cnpj, razao, ano

    def extract_rendimentos(self, text: str) -> list[RendimentoExtraido]:
        rendimentos: list[RendimentoExtraido] = []
        for section_pat, cat in [
            (_SECTION_TRIB_EXCLUSIVA, "tributacao_exclusiva"),
            (_SECTION_ISENTOS, "isento"),
            (_SECTION_TRIBUTAVEL, "tributavel"),
        ]:
            section = _find_section_text(text, section_pat)
            if section:
                rendimentos.extend(_extract_rendimentos_from_section(section, cat))
        return rendimentos

    def extract_saldos(self, text: str) -> list[SaldoExtraido]:
        saldos: list[SaldoExtraido] = []
        current_tipo = "investimento"
        for line in text.split("\n"):
            tipo_match = _TIPO_CONTA_PATTERN.search(line)
            if tipo_match:
                raw = unicodedata.normalize("NFKD", tipo_match.group(1).lower())
                raw = "".join(c for c in raw if not unicodedata.combining(c))
                if "corrente" in raw:
                    current_tipo = "corrente"
                elif "poupanc" in raw:
                    current_tipo = "poupanca"
                elif "corretora" in raw:
                    current_tipo = "corretora"
                else:
                    current_tipo = "investimento"
            for m in _SALDO_PATTERN.finditer(line):
                ano = int(m.group(1))
                valor = _parse_br_money(m.group(2))
                if valor and 2020 <= ano <= 2030:
                    saldos.append(SaldoExtraido(tipo_conta=current_tipo, ano=ano, valor=valor))
        return saldos

    def extract_rendimento_trabalho(self, text: str) -> RendimentoTrabalhoExtraido | None:
        if not _SECTION_HOLERITE.search(text):
            return None
        wk = RendimentoTrabalhoExtraido()
        for pattern, attr in [
            (_SALARIO_PATTERN, "rendimento_tributavel"),
            (_INSS_PATTERN, "contribuicao_previdenciaria"),
            (_IRRF_HOLERITE_PATTERN, "irrf"),
        ]:
            m = pattern.search(text)
            if m:
                parsed = _parse_br_money(m.group(1))
                if parsed:
                    setattr(wk, attr, parsed)
        return wk

    def extract_despesas_medicas(self, text: str) -> list[DespesaMedicaExtraido]:
        despesas: list[DespesaMedicaExtraido] = []
        for m in _SAUDE_GULOSA_PATTERN.finditer(text):
            digits = re.sub(r"[^\d]", "", m.group("cnpj"))
            if len(digits) == 14:
                cnpj = f"{digits[:2]}.{digits[2:5]}.{digits[5:8]}/{digits[8:12]}-{digits[12:14]}"
                valor = _parse_br_money(m.group("valor"))
                if cnpj and valor and valor > 0:
                    despesas.append(DespesaMedicaExtraido(
                        cnpj_prestador=cnpj,
                        razao_social_prestador="Prestador de Saúde Identificado por Regex",
                        valor_pago=valor,
                    ))
        return despesas


# ─── Alias standalone para testabilidade ──────────────────────────────────────

def _extract_saldos_from_text(text: str) -> list[SaldoExtraido]:
    """Wrapper standalone de extract_saldos para uso em testes."""
    return GenericParserStrategy().extract_saldos(text)

