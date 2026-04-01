"""
Serviço de ingestão de Informes de Rendimentos Financeiros em PDF.

Pipeline:
  1. Extrai texto de todas as páginas do PDF via pdfplumber
  2. Normaliza quebras de linha e espaços (PDF → texto limpo)
  3. Extrai via regex: CNPJ, Razão Social, Ano-Calendário
  4. Extrai blocos de rendimentos (tributação exclusiva, isentos, tributáveis)
  5. Extrai saldos de contas/aplicações em 31/12
  6. Persiste: RendimentoInforme + atualiza/cria ContaBancaria
"""

from __future__ import annotations

import io
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from typing import BinaryIO

import pdfplumber
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import ContaBancaria, Contribuinte, RendimentoInforme

logger = logging.getLogger(__name__)

TWO_PLACES = Decimal("0.01")


# ═══════════════════════════════════════════════════════════════════
#  Helpers de limpeza de texto
# ═══════════════════════════════════════════════════════════════════
def _normalize_text(raw: str) -> str:
    """
    Normaliza texto extraído de PDF:
      - Remove múltiplas quebras de linha consecutivas
      - Colapsa espaços múltiplos
      - Mantém quebras de linha simples para separar seções
    """
    # Substitui \r\n e \r por \n
    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    # Remove linhas que são só espaço
    lines = [line.rstrip() for line in text.split("\n")]
    # Colapsa 3+ quebras de linha em 2
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


def _clean_value_str(s: str) -> str:
    """Remove espaços e caracteres non-breaking de valores."""
    # Remove non-breaking spaces, thin spaces, etc.
    s = unicodedata.normalize("NFKD", s)
    s = re.sub(r"[\u00a0\u2007\u202f\u2009]", " ", s)
    return s.strip()


def _parse_br_money(value: str) -> Decimal | None:
    """
    Converte string monetária BR para Decimal.
    Trata: 'R$ 1.500,00', '1.500,00', '1500,00', '-200,50'
    """
    s = _clean_value_str(value)
    if not s or s == "-":
        return None

    negative = s.startswith("-") or "- " in s

    # Remove prefixo R$, espaços e sinal
    s = re.sub(r"^[\s\-]*R?\$?\s*", "", s, flags=re.IGNORECASE).strip()
    s = s.lstrip("-").strip()

    if not s:
        return None

    # Formato BR: ponto = milhar, vírgula = decimal
    if "," in s:
        s = s.replace(".", "")   # remove separador de milhar
        s = s.replace(",", ".")  # troca vírgula por ponto decimal
    # Se só tem ponto, pode ser decimal (1500.00) — mantém

    try:
        result = Decimal(s).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
        return -result if negative else result
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════════════
#  Regex patterns para Informes de Rendimentos
# ═══════════════════════════════════════════════════════════════════

# CNPJ: 00.000.000/0001-91 (com possíveis espaços/quebras no meio)
_CNPJ_PATTERN = re.compile(
    r"CNPJ[\s/MF:]*[\s:]*"
    r"(\d{2}[\s.]*\d{3}[\s.]*\d{3}[\s/]*\d{4}[\s-]*\d{2})",
    re.IGNORECASE,
)


# Ano-Calendário
_ANO_PATTERN = re.compile(
    r"ANO[\s-]*CALEND[ÁA]RIO[\s:DE]*(\d{4})",
    re.IGNORECASE,
)

# Seções do informe
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

# Próxima seção (para delimitar fim de uma seção)
_NEXT_SECTION = re.compile(
    r"^\s*\d+\.?\s*[-–]?\s*(?:RENDIMENTO|INFORMA[ÇC]|RELA[ÇC]|IMPOSTO|TOTAL|RESPONSÁVEL)",
    re.IGNORECASE | re.MULTILINE,
)

# Linha com valor monetário (tenta capturar descrição e valor)
# Exemplos:
#   Rendimentos de CDB .............. 1.234,56
#   01 Poupança                       567,89
#   Rendimentos de aplicações financeiras    R$ 1.234,56
_VALUE_LINE_PATTERN = re.compile(
    r"^(.+?)\s+"                                        # Descrição
    r"(R?\$?\s*[\d.,]+(?:,\d{2}))"                      # Valor monetário
    r"\s*$",
    re.MULTILINE,
)

# Valor IRRF na mesma linha ou próxima
_IRRF_PATTERN = re.compile(
    r"(?:IRRF|IR\s+RETIDO|IMPOSTO\s+(?:DE\s+)?RENDA\s+RETIDO)"
    r"[\s:]*R?\$?\s*([\d.,]+(?:,\d{2}))",
    re.IGNORECASE,
)

# Saldos em 31/12
# Exemplos:
#   Saldo em 31/12/2023  R$ 15.000,00
#   31/12/2024       18.500,00
#   Saldo em 31/12/2023: 15.000,00   Saldo em 31/12/2024: 18.500,00
_SALDO_PATTERN = re.compile(
    r"(?:SALDO[\s]*(?:EM|:)?\s*)?"
    r"31[\s/]*12[\s/]*(\d{4})"
    r"[\s:]*R?\$?\s*([\d.,]+(?:,\d{2}))",
    re.IGNORECASE,
)

# Tipo de conta/aplicação antes dos saldos
_TIPO_CONTA_PATTERN = re.compile(
    r"(CONTA\s+CORRENTE|POUPAN[ÇC]A|CDB|RDB|LCI|LCA|FUNDO|"
    r"APLICA[ÇC][ÃA]O|INVESTIMENTO|TESOURO|RENDA\s+FIXA|"
    r"A[ÇC][ÕO]ES|FII|CORRETORA)",
    re.IGNORECASE,
)


# ═══════════════════════════════════════════════════════════════════
#  Estruturas de dados
# ═══════════════════════════════════════════════════════════════════
@dataclass
class RendimentoExtraido:
    """Um rendimento extraído do PDF."""
    categoria: str         # tributacao_exclusiva | isento | tributavel
    descricao: str
    valor: Decimal
    irrf: Decimal = Decimal("0.00")


@dataclass
class SaldoExtraido:
    """Saldo extraído do PDF."""
    tipo_conta: str        # corrente, poupanca, investimento, etc.
    ano: int
    valor: Decimal


@dataclass
class InformeExtraido:
    """Resultado completo da extração de um PDF."""
    cnpj_fonte: str | None = None
    razao_social: str | None = None
    ano_calendario: int | None = None
    rendimentos: list[RendimentoExtraido] = field(default_factory=list)
    saldos: list[SaldoExtraido] = field(default_factory=list)
    texto_bruto: str = ""
    erros: list[str] = field(default_factory=list)


@dataclass
class InformeImportResult:
    """Resultado final: extração + persistência."""
    cnpj_fonte: str | None = None
    razao_social: str | None = None
    ano_calendario: int | None = None
    rendimentos_inseridos: int = 0
    saldos_atualizados: int = 0
    erros: list[str] = field(default_factory=list)
    rendimentos_detalhe: list[dict] = field(default_factory=list)
    saldos_detalhe: list[dict] = field(default_factory=list)


# ═══════════════════════════════════════════════════════════════════
#  Extração de texto do PDF
# ═══════════════════════════════════════════════════════════════════
def extract_text_from_pdf(source: BinaryIO | bytes) -> str:
    """
    Extrai todo o texto de um PDF usando pdfplumber.
    Retorna string com texto concatenado de todas as páginas.
    """
    if isinstance(source, bytes):
        source = io.BytesIO(source)

    full_text = []
    with pdfplumber.open(source) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                full_text.append(text)

    return "\n\n".join(full_text)


# ═══════════════════════════════════════════════════════════════════
#  Parsing do texto extraído
# ═══════════════════════════════════════════════════════════════════
def _extract_cnpj(text: str) -> str | None:
    """Extrai e normaliza CNPJ do texto."""
    match = _CNPJ_PATTERN.search(text)
    if not match:
        return None
    raw = match.group(1)
    # Remove espaços e normaliza formato
    digits = re.sub(r"[^\d]", "", raw)
    if len(digits) != 14:
        return None
    return f"{digits[:2]}.{digits[2:5]}.{digits[5:8]}/{digits[8:12]}-{digits[12:14]}"


def _extract_razao_social(text: str) -> str | None:
    """Extrai Razão Social do texto, tentando padrões específicos."""
    patterns = [
        re.compile(r"(?:RAZ[ÃA]O\s*SOCIAL|NOME\s*EMPRESARIAL)[\s:]*(.+?)(?:\n|CNPJ|$)", re.IGNORECASE),
        re.compile(r"FONTE\s*PAGADORA[\s:]*(.+?)(?:\n|CNPJ|$)", re.IGNORECASE)
    ]
    
    for pat in patterns:
        for match in pat.finditer(text):
            raw = match.group(1).strip()
            # Descarta capturas que contenham CNPJ ou sejam só números/símbolos
            if "CNPJ" in raw.upper() or re.match(r"^[\d.\-/:\s]+$", raw):
                continue
            
            # Remove espaços múltiplos e limpa pontuação final
            raw = re.sub(r"\s+", " ", raw).strip().rstrip(".")
            if len(raw) > 2:
                return raw
                
    return None


def _extract_ano(text: str) -> int | None:
    """Extrai ano-calendário do texto."""
    match = _ANO_PATTERN.search(text)
    if not match:
        return None
    year = int(match.group(1))
    if 2020 <= year <= 2030:
        return year
    return None


def _find_section_text(text: str, section_pattern: re.Pattern) -> str | None:
    """
    Encontra o texto de uma seção, delimitada pelo próximo cabeçalho.
    Retorna o conteúdo da seção ou None.
    """
    match = section_pattern.search(text)
    if not match:
        return None

    start = match.end()
    # Busca o fim da seção (próximo cabeçalho de seção)
    remaining = text[start:]
    end_match = _NEXT_SECTION.search(remaining)
    if end_match:
        section = remaining[:end_match.start()]
    else:
        section = remaining

    return section.strip()


def _extract_rendimentos_from_section(
    section_text: str, categoria: str
) -> list[RendimentoExtraido]:
    """
    Extrai pares (descrição, valor) de uma seção do informe.
    Lida com formatos tabulares e quebras de linha em PDFs.
    """
    rendimentos = []

    # Pré-tratamento: remove linhas de pontos/traços (separadores visuais)
    cleaned = re.sub(r"\.{3,}", " ", section_text)
    cleaned = re.sub(r"-{3,}", " ", cleaned)
    cleaned = re.sub(r"_{3,}", " ", cleaned)
    # Colapsa múltiplos espaços
    cleaned = re.sub(r"[ \t]{2,}", "  ", cleaned)

    # Tenta extrair com o padrão principal
    for match in _VALUE_LINE_PATTERN.finditer(cleaned):
        desc = match.group(1).strip()
        raw_valor = match.group(2)

        # Ignora linhas de cabeçalho
        desc_lower = desc.lower()
        if any(kw in desc_lower for kw in [
            "tipo de rendimento", "discriminação", "valor (r$)",
            "descrição", "valor r$", "código",
        ]):
            continue

        # Ignora se descrição é só número/código
        if re.match(r"^\d{1,3}$", desc.strip()):
            # Pode ser um código de linha — tenta juntar com contexto
            pass

        valor = _parse_br_money(raw_valor)
        if valor is not None and valor > 0:
            # Limpa descrição: remove código numérico inicial
            desc = re.sub(r"^\d{1,3}\s+", "", desc).strip()
            rendimentos.append(RendimentoExtraido(
                categoria=categoria,
                descricao=desc,
                valor=valor,
            ))

    # Se nenhum rendimento encontrado, tenta abordagem mais flexível
    # para textos com formato tabular quebrado
    if not rendimentos:
        lines = cleaned.split("\n")
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            # Procura valor monetário no fim da linha
            money_match = re.search(
                r"(R?\$?\s*[\d.]+,\d{2})\s*$", line
            )
            if money_match:
                raw_valor = money_match.group(1)
                desc = line[:money_match.start()].strip()
                # Remove código numérico inicial
                desc = re.sub(r"^\d{1,3}\s+", "", desc).strip()

                if desc:
                    valor = _parse_br_money(raw_valor)
                    if valor is not None and valor > 0:
                        desc_lower = desc.lower()
                        if not any(kw in desc_lower for kw in [
                            "tipo de rendimento", "valor (r$)", "valor r$",
                        ]):
                            rendimentos.append(RendimentoExtraido(
                                categoria=categoria,
                                descricao=desc,
                                valor=valor,
                            ))
            i += 1

    return rendimentos


def _extract_saldos(text: str) -> list[SaldoExtraido]:
    """
    Extrai saldos em 31/12 do texto.
    Tenta identificar o tipo de conta/aplicação pelo contexto.
    """
    saldos = []

    # Divide o texto em blocos para identificar tipo de conta por contexto
    lines = text.split("\n")
    current_tipo = "investimento"  # default

    for i, line in enumerate(lines):
        # Detecta tipo de conta
        tipo_match = _TIPO_CONTA_PATTERN.search(line)
        if tipo_match:
            raw_tipo = tipo_match.group(1).lower()
            raw_tipo = unicodedata.normalize("NFKD", raw_tipo)
            raw_tipo = "".join(c for c in raw_tipo if not unicodedata.combining(c))

            if "corrente" in raw_tipo:
                current_tipo = "corrente"
            elif "poupanc" in raw_tipo:
                current_tipo = "poupanca"
            elif "corretora" in raw_tipo:
                current_tipo = "corretora"
            else:
                current_tipo = "investimento"

        # Procura saldos na linha
        for saldo_match in _SALDO_PATTERN.finditer(line):
            ano = int(saldo_match.group(1))
            valor = _parse_br_money(saldo_match.group(2))
            if valor is not None and 2020 <= ano <= 2030:
                saldos.append(SaldoExtraido(
                    tipo_conta=current_tipo,
                    ano=ano,
                    valor=valor,
                ))

    return saldos


def parse_informe_text(text: str) -> InformeExtraido:
    """
    Faz o parse completo do texto extraído de um informe de rendimentos.
    É a função núcleo testável sem depender de pdfplumber.

    Args:
        text: Texto bruto extraído do PDF.

    Returns:
        InformeExtraido com todos os dados encontrados.
    """
    result = InformeExtraido(texto_bruto=text)
    normalized = _normalize_text(text)

    # ── 1. Dados da fonte pagadora ──────────────────────────────────
    result.cnpj_fonte = _extract_cnpj(normalized)
    if not result.cnpj_fonte:
        result.erros.append("CNPJ da fonte pagadora não encontrado")

    result.razao_social = _extract_razao_social(normalized)
    if not result.razao_social:
        result.erros.append("Razão Social não encontrada")

    result.ano_calendario = _extract_ano(normalized)
    if not result.ano_calendario:
        result.erros.append("Ano-calendário não encontrado")

    # ── 2. Rendimentos tributação exclusiva ──────────────────────────
    section = _find_section_text(normalized, _SECTION_TRIB_EXCLUSIVA)
    if section:
        rends = _extract_rendimentos_from_section(section, "tributacao_exclusiva")
        result.rendimentos.extend(rends)
    else:
        result.erros.append(
            "Seção 'Rendimentos Tributação Exclusiva/Definitiva' não encontrada"
        )

    # ── 3. Rendimentos isentos ──────────────────────────────────────
    section = _find_section_text(normalized, _SECTION_ISENTOS)
    if section:
        rends = _extract_rendimentos_from_section(section, "isento")
        result.rendimentos.extend(rends)
    else:
        result.erros.append(
            "Seção 'Rendimentos Isentos e Não Tributáveis' não encontrada"
        )

    # ── 4. Rendimentos tributáveis (opcional, nem todo informe tem) ──
    section = _find_section_text(normalized, _SECTION_TRIBUTAVEL)
    if section:
        rends = _extract_rendimentos_from_section(section, "tributavel")
        result.rendimentos.extend(rends)

    # ── 5. Saldos ───────────────────────────────────────────────────
    result.saldos = _extract_saldos(normalized)

    return result


# ═══════════════════════════════════════════════════════════════════
#  Persistência
# ═══════════════════════════════════════════════════════════════════
def _persist_rendimentos(
    informe: InformeExtraido,
    contribuinte_id: int,
    db: Session,
) -> int:
    """Insere rendimentos extraídos no banco. Retorna quantidade inserida."""
    if not informe.cnpj_fonte or not informe.razao_social or not informe.ano_calendario:
        return 0

    count = 0
    for rend in informe.rendimentos:
        obj = RendimentoInforme(
            contribuinte_id=contribuinte_id,
            cnpj_fonte=informe.cnpj_fonte,
            razao_social_fonte=informe.razao_social,
            ano_calendario=informe.ano_calendario,
            categoria=rend.categoria,
            descricao=rend.descricao,
            valor=rend.valor,
            irrf=rend.irrf,
        )
        db.add(obj)
        count += 1

    if count:
        db.flush()

    return count


def _persist_saldos(
    informe: InformeExtraido,
    contribuinte_id: int,
    db: Session,
) -> int:
    """
    Upsert saldos na tabela ContaBancaria.
    Agrupa saldos por tipo de conta e atualiza/cria registros.
    """
    if not informe.cnpj_fonte or not informe.razao_social:
        return 0

    # Agrupa saldos por tipo de conta
    saldos_por_tipo: dict[str, dict[int, Decimal]] = {}
    for saldo in informe.saldos:
        tipo_key = saldo.tipo_conta
        if tipo_key not in saldos_por_tipo:
            saldos_por_tipo[tipo_key] = {}
        saldos_por_tipo[tipo_key][saldo.ano] = saldo.valor

    count = 0
    ano_ref = informe.ano_calendario or max(
        (s.ano for s in informe.saldos), default=2025
    )

    for tipo_conta, saldos_ano in saldos_por_tipo.items():
        # Mapeia para tipo_conta compatível com o CHECK constraint
        tipo_db = tipo_conta
        if tipo_db not in ("corrente", "poupanca", "investimento", "corretora"):
            tipo_db = "investimento"

        saldo_anterior = saldos_ano.get(ano_ref - 1, Decimal("0.00"))
        saldo_atual = saldos_ano.get(ano_ref, Decimal("0.00"))

        # Procura conta existente
        existing = db.scalars(
            select(ContaBancaria).where(
                ContaBancaria.contribuinte_id == contribuinte_id,
                ContaBancaria.instituicao == informe.razao_social,
                ContaBancaria.tipo_conta == tipo_db,
                ContaBancaria.ano_referencia == ano_ref,
            )
        ).first()

        if existing:
            existing.saldo_31_12_anterior = saldo_anterior
            existing.saldo_31_12_atual = saldo_atual
        else:
            obj = ContaBancaria(
                contribuinte_id=contribuinte_id,
                instituicao=informe.razao_social,
                tipo_conta=tipo_db,
                saldo_31_12_anterior=saldo_anterior,
                saldo_31_12_atual=saldo_atual,
                ano_referencia=ano_ref,
            )
            db.add(obj)

        count += 1

    if count:
        db.flush()

    return count


# ═══════════════════════════════════════════════════════════════════
#  Pipeline principal
# ═══════════════════════════════════════════════════════════════════
def ingest_informe_pdf(
    file_content: BinaryIO,
    contribuinte_id: int,
    db: Session,
) -> InformeImportResult:
    """
    Orquestra o pipeline completo: PDF → texto → parse → persist.
    Chamada pela rota POST /upload/informe-pdf.
    """
    result = InformeImportResult()

    # Valida contribuinte
    contrib = db.get(Contribuinte, contribuinte_id)
    if contrib is None:
        result.erros.append(f"Contribuinte id={contribuinte_id} não encontrado.")
        return result

    # Extrai texto do PDF
    try:
        text = extract_text_from_pdf(file_content)
    except Exception as e:
        result.erros.append(f"Erro ao extrair texto do PDF: {e}")
        return result

    if not text.strip():
        result.erros.append("O PDF não contém texto extraível (pode ser escaneado).")
        return result

    # Parse do texto
    informe = parse_informe_text(text)
    result.cnpj_fonte = informe.cnpj_fonte
    result.razao_social = informe.razao_social
    result.ano_calendario = informe.ano_calendario
    result.erros.extend(informe.erros)

    # Persist rendimentos
    result.rendimentos_inseridos = _persist_rendimentos(informe, contribuinte_id, db)
    for rend in informe.rendimentos:
        result.rendimentos_detalhe.append({
            "categoria": rend.categoria,
            "descricao": rend.descricao,
            "valor": str(rend.valor),
            "irrf": str(rend.irrf),
        })

    # Persist saldos
    result.saldos_atualizados = _persist_saldos(informe, contribuinte_id, db)
    for saldo in informe.saldos:
        result.saldos_detalhe.append({
            "tipo_conta": saldo.tipo_conta,
            "ano": saldo.ano,
            "valor": str(saldo.valor),
        })

    db.commit()
    return result
