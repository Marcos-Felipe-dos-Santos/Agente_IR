"""
Serviço de ingestão de dados da B3 — CSV de movimentação/negociação.

Pipeline:
  1. Lê o CSV (upload ou caminho local)
  2. Detecta automaticamente o layout de colunas (negociação vs movimentação)
  3. Limpa dados: espaços, strings monetárias BR → Decimal
  4. Categoriza operações (compra, venda, desdobramento/grupamento)
  5. Calcula Preço Médio de Aquisição ponderado por ticker
  6. Insere no banco via SQLAlchemy respeitando FK
"""

from __future__ import annotations

import io
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import BinaryIO

import pandas as pd
from sqlalchemy.orm import Session

from app.models.entities import Contribuinte, OperacaoB3

logger = logging.getLogger(__name__)

# ── Constantes ──────────────────────────────────────────────────────
TWO_PLACES = Decimal("0.01")
EIGHT_PLACES = Decimal("0.00000001")

# Regex para limpar strings monetárias brasileiras
# Captura: "R$ 1.500,00", "R$1500,00", "1.500,00", "-1.500,00", "- R$ 500,00"
_MONEY_RE = re.compile(r"^\s*-?\s*R?\$?\s*", re.IGNORECASE)

# Mapeamento de nomes de colunas conhecidos (B3 varia o nome entre exports)
_COLUMN_ALIASES: dict[str, list[str]] = {
    "data": [
        "data do negócio", "data do negocio", "data negócio",
        "data negocio", "data", "data pregão", "data pregao",
        "data do pregão", "data do pregao",
    ],
    "tipo": [
        "tipo de movimentação", "tipo de movimentacao", "tipo movimentação",
        "tipo movimentacao", "movimentação", "movimentacao",
        "entrada/saída", "entrada/saida", "tipo",
        "compra/venda", "c/v",
    ],
    "ticker": [
        "código de negociação", "codigo de negociacao",
        "código negociação", "codigo negociacao",
        "código", "codigo", "ticker", "produto", "ativo",
    ],
    "quantidade": [
        "quantidade", "qtde", "qtd", "qtde.", "qtd.",
    ],
    "preco": [
        "preço", "preco", "preço unitário", "preco unitario",
        "preço/ajuste", "preco/ajuste", "preço (r$)", "preco (r$)",
        "preço unitário (r$)", "preco unitario (r$)",
    ],
    "valor": [
        "valor da operação", "valor da operacao", "valor operação",
        "valor operacao", "valor total", "valor total (r$)",
        "valor (r$)", "valor",
    ],
    "corretora": [
        "instituição", "instituicao", "corretora",
        "participante", "intermediário", "intermediario",
    ],
    "mercado": [
        "mercado", "praça", "praca",
    ],
}

# Palavras-chave para classificar tipo de operação
_COMPRA_KEYWORDS = {"compra", "credito", "crédito", "c", "transferência - Loss", "bonificação em ativos"}
_VENDA_KEYWORDS = {"venda", "debito", "débito", "v"}
_DESDOBRAMENTO_KEYWORDS = {"desdobramento", "desdobro", "grupamento", "split", "bonificação", "bonificacao"}


# ── Helpers ─────────────────────────────────────────────────────────
def _normalize_col_name(name: str) -> str:
    """Remove acentos, converte para minúscula e limpa espaços."""
    name = name.strip().lower()
    # Remove acentos
    nfkd = unicodedata.normalize("NFKD", name)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _parse_br_money(value) -> Decimal | None:
    """
    Converte string monetária BR para Decimal.
      'R$ 1.500,00' → Decimal('1500.00')
      '1.500,00'    → Decimal('1500.00')
      '-R$ 200,50'  → Decimal('-200.50')
    """
    if pd.isna(value):
        return None
    if isinstance(value, (int, float)):
        return Decimal(str(value)).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)

    s = str(value).strip()
    if not s:
        return None

    # Detecta sinal negativo
    negative = "-" in s

    # Remove prefixo R$, espaços e sinal
    s = _MONEY_RE.sub("", s).strip().lstrip("-").strip()

    # Se contém vírgula, é formato BR (1.500,00)
    if "," in s:
        s = s.replace(".", "")   # remove separador de milhar
        s = s.replace(",", ".")  # troca vírgula decimal por ponto
    # senão, o ponto já é decimal (1500.00)

    if not s:
        return None

    result = Decimal(s).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
    return -result if negative else result


def _parse_br_date(value) -> date | None:
    """Converte datas brasileiras (dd/mm/yyyy, dd-mm-yyyy, yyyy-mm-dd) para date."""
    if pd.isna(value):
        return None
    if isinstance(value, (date, datetime)):
        return value if isinstance(value, date) else value.date()

    s = str(value).strip()
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d/%m/%y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Formato de data não reconhecido: '{s}'")


def _classify_operation(raw_type: str) -> str:
    """
    Classifica a operação como 'compra', 'venda' ou 'desdobramento'.
    Retorna o tipo normalizado.
    """
    normalized = _normalize_col_name(raw_type)
    if any(kw in normalized for kw in _DESDOBRAMENTO_KEYWORDS):
        return "desdobramento"
    if any(kw in normalized for kw in _COMPRA_KEYWORDS):
        return "compra"
    if any(kw in normalized for kw in _VENDA_KEYWORDS):
        return "venda"
    # Fallback: se contém "credito" → compra, "debito" → venda
    logger.warning("Tipo de operação não reconhecido: '%s' → tratado como 'compra'", raw_type)
    return "compra"


def _resolve_columns(df: pd.DataFrame) -> dict[str, str]:
    """
    Mapeia colunas padrão internas para os nomes reais do DataFrame.
    Retorna dict {nome_interno: nome_real_no_df}.
    Lança ValueError se colunas obrigatórias não forem encontradas.
    """
    normalized_cols = {_normalize_col_name(c): c for c in df.columns}
    mapping: dict[str, str] = {}

    for internal_name, aliases in _COLUMN_ALIASES.items():
        for alias in aliases:
            norm_alias = _normalize_col_name(alias)
            if norm_alias in normalized_cols:
                mapping[internal_name] = normalized_cols[norm_alias]
                break

    # Colunas obrigatórias
    required = {"data", "tipo", "ticker", "quantidade", "preco"}
    missing = required - set(mapping.keys())
    if missing:
        available = list(df.columns)
        raise ValueError(
            f"Colunas obrigatórias não encontradas no CSV: {missing}. "
            f"Colunas disponíveis: {available}"
        )

    return mapping


# ── Resultado do processamento ──────────────────────────────────────
@dataclass
class PrecoMedioTicker:
    """Estado do preço médio ponderado de um ativo."""
    ticker: str
    quantidade_total: Decimal = Decimal("0")
    custo_total: Decimal = Decimal("0")

    @property
    def preco_medio(self) -> Decimal:
        if self.quantidade_total <= 0:
            return Decimal("0")
        return (self.custo_total / self.quantidade_total).quantize(
            EIGHT_PLACES, rounding=ROUND_HALF_UP
        )

    def compra(self, qtd: Decimal, preco: Decimal, custos: Decimal) -> None:
        """Atualiza preço médio com uma nova compra."""
        custo_operacao = (qtd * preco) + custos
        self.quantidade_total += qtd
        self.custo_total += custo_operacao

    def venda(self, qtd: Decimal) -> Decimal:
        """
        Registra venda. Retorna o custo de aquisição proporcional à venda.
        Não altera o preço médio, apenas reduz a posição.
        """
        if qtd > self.quantidade_total:
            logger.warning(
                "Venda de %s excede posição de %s para ticker (possível day-trade ou posição anterior)",
                qtd, self.quantidade_total,
            )
        custo_proporcional = (qtd * self.preco_medio).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
        self.quantidade_total = max(Decimal("0"), self.quantidade_total - qtd)
        self.custo_total = max(Decimal("0"), self.custo_total - custo_proporcional)
        return custo_proporcional


@dataclass
class B3ImportResult:
    """Resultado do processo de importação."""
    total_linhas_csv: int = 0
    operacoes_inseridas: int = 0
    operacoes_ignoradas: int = 0
    desdobramentos_detectados: int = 0
    erros: list[str] = field(default_factory=list)
    precos_medios: dict[str, dict] = field(default_factory=dict)


# ── Pipeline principal ──────────────────────────────────────────────
def parse_b3_csv(
    source: BinaryIO | str | Path,
    encoding: str = "utf-8",
) -> pd.DataFrame:
    """
    Lê e limpa o CSV da B3, retornando um DataFrame padronizado.

    Args:
        source: arquivo binário (upload), caminho local ou string path.
        encoding: encoding do CSV (padrão utf-8, B3 às vezes usa latin-1).

    Returns:
        DataFrame com colunas padronizadas e dados limpos.
    """
    # ── 1. Leitura ──────────────────────────────────────────────────
    read_kwargs = {
        "sep": None,           # autodetect ; ou ,
        "engine": "python",    # necessário para sep=None
        "encoding": encoding,
        "dtype": str,          # tudo como string para limpeza manual
        "skipinitialspace": True,
    }

    if isinstance(source, (str, Path)):
        df = pd.read_csv(source, **read_kwargs)
    else:
        # Para upload via FastAPI (SpooledTemporaryFile / BytesIO)
        content = source.read()
        # Tenta utf-8, fallback para latin-1
        for enc in [encoding, "latin-1", "cp1252"]:
            try:
                text = content.decode(enc)
                break
            except (UnicodeDecodeError, AttributeError):
                continue
        else:
            text = content.decode("utf-8", errors="replace")

        df = pd.read_csv(io.StringIO(text), **{k: v for k, v in read_kwargs.items() if k != "encoding"})

    if df.empty:
        raise ValueError("O CSV está vazio ou não contém dados válidos.")

    # ── 2. Limpeza de colunas ───────────────────────────────────────
    # Remove espaços em branco dos nomes de colunas
    df.columns = [c.strip() for c in df.columns]

    # Remove linhas completamente vazias
    df = df.dropna(how="all").reset_index(drop=True)

    # Strip em todas as células string
    for col in df.columns:
        df[col] = df[col].apply(lambda x: x.strip() if isinstance(x, str) else x)

    return df


def process_b3_operations(
    df: pd.DataFrame,
    contribuinte_id: int,
    db: Session,
    corretora_override: str | None = None,
) -> B3ImportResult:
    """
    Processa DataFrame da B3, calcula preço médio e insere no banco.

    Args:
        df: DataFrame limpo (saída de parse_b3_csv).
        contribuinte_id: FK do contribuinte.
        db: Sessão SQLAlchemy.
        corretora_override: Se fornecido, sobrescreve a corretora do CSV.

    Returns:
        B3ImportResult com estatísticas do processamento.
    """
    result = B3ImportResult(total_linhas_csv=len(df))

    # Valida que o contribuinte existe
    contrib = db.get(Contribuinte, contribuinte_id)
    if contrib is None:
        result.erros.append(f"Contribuinte id={contribuinte_id} não encontrado.")
        return result

    # Resolve mapeamento de colunas
    try:
        col_map = _resolve_columns(df)
    except ValueError as e:
        result.erros.append(str(e))
        return result

    col_data = col_map["data"]
    col_tipo = col_map["tipo"]
    col_ticker = col_map["ticker"]
    col_qtd = col_map["quantidade"]
    col_preco = col_map["preco"]
    col_valor = col_map.get("valor")
    col_corretora = col_map.get("corretora")

    # Estado do preço médio por ticker
    carteira: dict[str, PrecoMedioTicker] = {}

    operacoes_para_inserir: list[OperacaoB3] = []

    for idx, row in df.iterrows():
        line_num = idx + 2  # +2: header + 0-index
        try:
            # ── Parse dos campos ────────────────────────────────────
            data_op = _parse_br_date(row[col_data])
            if data_op is None:
                result.erros.append(f"Linha {line_num}: data inválida '{row[col_data]}'")
                result.operacoes_ignoradas += 1
                continue

            raw_tipo = str(row[col_tipo]).strip()
            tipo_op = _classify_operation(raw_tipo)

            ticker = str(row[col_ticker]).strip().upper()
            if not ticker or ticker == "NAN":
                result.operacoes_ignoradas += 1
                continue

            qtd = _parse_br_money(row[col_qtd])
            if qtd is None or qtd <= 0:
                result.erros.append(f"Linha {line_num}: quantidade inválida '{row[col_qtd]}'")
                result.operacoes_ignoradas += 1
                continue
            qtd = qtd.quantize(EIGHT_PLACES, rounding=ROUND_HALF_UP)

            preco = _parse_br_money(row[col_preco])
            if preco is None or preco < 0:
                result.erros.append(f"Linha {line_num}: preço inválido '{row[col_preco]}'")
                result.operacoes_ignoradas += 1
                continue
            preco = preco.quantize(EIGHT_PLACES, rounding=ROUND_HALF_UP)

            # Valor total: prefere coluna do CSV, senão calcula
            if col_valor and not pd.isna(row.get(col_valor)):
                valor_total = _parse_br_money(row[col_valor])
                if valor_total is None:
                    valor_total = (qtd * preco).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
            else:
                valor_total = (qtd * preco).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)

            # Valor total deve ser positivo (absoluto)
            valor_total = abs(valor_total)

            # Corretora
            corretora = corretora_override
            if not corretora and col_corretora:
                raw_corr = row.get(col_corretora)
                if not pd.isna(raw_corr):
                    corretora = str(raw_corr).strip() or None

            # ── Desdobramento/Grupamento ────────────────────────────
            if tipo_op == "desdobramento":
                result.desdobramentos_detectados += 1
                logger.info(
                    "Linha %d: desdobramento/grupamento detectado para %s — "
                    "requer ajuste manual do preço médio",
                    line_num, ticker,
                )
                result.operacoes_ignoradas += 1
                continue

            # ── Custos operacionais ─────────────────────────────────
            # O CSV padrão da B3 não traz custos separados por linha.
            # Eles são informados na nota de corretagem. Aqui usamos 0
            # e permitem ajuste posterior. Em caso de nota de corretagem,
            # o custo pode ser rateado proporcionalmente.
            custos = Decimal("0.00")

            # ── Preço médio ─────────────────────────────────────────
            if ticker not in carteira:
                carteira[ticker] = PrecoMedioTicker(ticker=ticker)

            pm = carteira[ticker]

            if tipo_op == "compra":
                pm.compra(qtd, preco, custos)
            elif tipo_op == "venda":
                pm.venda(qtd)

            # ── Monta objeto ORM ────────────────────────────────────
            op = OperacaoB3(
                contribuinte_id=contribuinte_id,
                data_operacao=data_op,
                tipo_operacao=tipo_op,
                ticker=ticker,
                quantidade=qtd,
                preco_unitario=preco,
                valor_total=valor_total,
                custos_operacionais=custos,
                corretora=corretora,
            )
            operacoes_para_inserir.append(op)

        except Exception as e:
            result.erros.append(f"Linha {line_num}: erro inesperado — {e}")
            result.operacoes_ignoradas += 1
            continue

    # ── Inserção em lote no banco ───────────────────────────────────
    if operacoes_para_inserir:
        db.add_all(operacoes_para_inserir)
        db.commit()
        result.operacoes_inseridas = len(operacoes_para_inserir)

    # ── Preço médio final por ticker ────────────────────────────────
    for ticker, pm in carteira.items():
        result.precos_medios[ticker] = {
            "preco_medio": str(pm.preco_medio),
            "quantidade_em_carteira": str(pm.quantidade_total),
            "custo_total": str(pm.custo_total.quantize(TWO_PLACES)),
        }

    return result


# ── Função de conveniência para upload via API ──────────────────────
def ingest_b3_csv_upload(
    file_content: BinaryIO,
    contribuinte_id: int,
    db: Session,
    encoding: str = "utf-8",
    corretora_override: str | None = None,
) -> B3ImportResult:
    """
    Orquestra o pipeline completo: parse → process → persist.
    Chamada pela rota POST /upload/b3-csv.
    """
    df = parse_b3_csv(file_content, encoding=encoding)
    return process_b3_operations(
        df,
        contribuinte_id=contribuinte_id,
        db=db,
        corretora_override=corretora_override,
    )
