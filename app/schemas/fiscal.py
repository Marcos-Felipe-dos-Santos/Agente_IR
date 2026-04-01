"""
Schemas Pydantic — validação estrita de entrada/saída.

Convenções:
  • *Create  → payload de criação (POST)
  • *Update  → payload de atualização (PATCH)
  • *Read    → resposta da API (inclui id e timestamps)

Todos os schemas usam `model_config = ConfigDict(strict=True)` para
rejeitar coerções implícitas (ex.: string "123" como int).
Valores monetários são validados como Decimal com 2 casas.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Annotated

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
)


# ── Enums ───────────────────────────────────────────────────────────
class TipoConta(str, Enum):
    corrente = "corrente"
    poupanca = "poupanca"
    investimento = "investimento"
    corretora = "corretora"


class TipoOperacao(str, Enum):
    compra = "compra"
    venda = "venda"


class TipoProvento(str, Enum):
    dividendo = "dividendo"
    jcp = "jcp"


# ── Tipos anotados reutilizáveis ────────────────────────────────────
MonetaryBR = Annotated[
    Decimal, Field(ge=Decimal("0"), max_digits=15, decimal_places=2)
]
Qty8 = Annotated[
    Decimal, Field(gt=Decimal("0"), max_digits=18, decimal_places=8)
]
Price8 = Annotated[
    Decimal, Field(ge=Decimal("0"), max_digits=18, decimal_places=8)
]

CPF_REGEX = re.compile(r"^\d{3}\.\d{3}\.\d{3}-\d{2}$")
CNPJ_REGEX = re.compile(r"^\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}$")


# ═══════════════════════════════════════════════════════════════════
#  Contribuinte
# ═══════════════════════════════════════════════════════════════════
class ContribuinteCreate(BaseModel):
    model_config = ConfigDict(strict=True)

    cpf: str = Field(..., min_length=14, max_length=14, examples=["123.456.789-00"])
    nome_completo: str = Field(..., min_length=2, max_length=200)
    data_nascimento: date
    titulo_eleitor: str | None = Field(default=None, max_length=20)
    endereco: str | None = None
    ocupacao_principal: str | None = Field(default=None, max_length=100)
    ano_exercicio: int = Field(..., ge=2020, le=2030)

    @field_validator("cpf")
    @classmethod
    def _validar_cpf(cls, v: str) -> str:
        if not CPF_REGEX.match(v):
            raise ValueError("CPF deve estar no formato 000.000.000-00")
        return v


class ContribuinteUpdate(BaseModel):
    model_config = ConfigDict(strict=True)

    nome_completo: str | None = Field(default=None, min_length=2, max_length=200)
    titulo_eleitor: str | None = None
    endereco: str | None = None
    ocupacao_principal: str | None = None


class ContribuinteRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    cpf: str
    nome_completo: str
    data_nascimento: date
    titulo_eleitor: str | None
    endereco: str | None
    ocupacao_principal: str | None
    ano_exercicio: int
    created_at: datetime
    updated_at: datetime


# ═══════════════════════════════════════════════════════════════════
#  ContaBancaria
# ═══════════════════════════════════════════════════════════════════
class ContaBancariaCreate(BaseModel):
    model_config = ConfigDict(strict=True)

    contribuinte_id: int
    instituicao: str = Field(..., min_length=2, max_length=100)
    codigo_banco: str | None = Field(default=None, max_length=10)
    agencia: str | None = Field(default=None, max_length=20)
    conta: str | None = Field(default=None, max_length=30)
    tipo_conta: TipoConta
    saldo_31_12_anterior: MonetaryBR = Decimal("0.00")
    saldo_31_12_atual: MonetaryBR = Decimal("0.00")
    ano_referencia: int = Field(..., ge=2020, le=2030)


class ContaBancariaRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    contribuinte_id: int
    instituicao: str
    codigo_banco: str | None
    agencia: str | None
    conta: str | None
    tipo_conta: str
    saldo_31_12_anterior: Decimal
    saldo_31_12_atual: Decimal
    ano_referencia: int
    created_at: datetime
    updated_at: datetime


# ═══════════════════════════════════════════════════════════════════
#  OperacaoB3
# ═══════════════════════════════════════════════════════════════════
class OperacaoB3Create(BaseModel):
    model_config = ConfigDict(strict=True)

    contribuinte_id: int
    data_operacao: date
    tipo_operacao: TipoOperacao
    ticker: str = Field(..., min_length=1, max_length=20)
    quantidade: Qty8
    preco_unitario: Price8
    valor_total: MonetaryBR
    custos_operacionais: MonetaryBR = Decimal("0.00")
    nota_corretagem: str | None = Field(default=None, max_length=50)
    corretora: str | None = Field(default=None, max_length=100)


class OperacaoB3Read(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    contribuinte_id: int
    data_operacao: date
    tipo_operacao: str
    ticker: str
    quantidade: Decimal
    preco_unitario: Decimal
    valor_total: Decimal
    custos_operacionais: Decimal
    nota_corretagem: str | None
    corretora: str | None
    created_at: datetime
    updated_at: datetime


# ═══════════════════════════════════════════════════════════════════
#  AtivoCripto
# ═══════════════════════════════════════════════════════════════════
class AtivoCriptoCreate(BaseModel):
    model_config = ConfigDict(strict=True)

    contribuinte_id: int
    data_operacao: date
    tipo_operacao: TipoOperacao
    moeda: str = Field(..., min_length=1, max_length=20, examples=["BTC", "ETH"])
    quantidade: Qty8
    preco_unitario_brl: Price8
    valor_total_brl: MonetaryBR
    exchange: str | None = Field(default=None, max_length=100)
    custo_aquisicao_medio: Price8 | None = None


class AtivoCriptoRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    contribuinte_id: int
    data_operacao: date
    tipo_operacao: str
    moeda: str
    quantidade: Decimal
    preco_unitario_brl: Decimal
    valor_total_brl: Decimal
    exchange: str | None
    custo_aquisicao_medio: Decimal | None
    created_at: datetime
    updated_at: datetime


# ═══════════════════════════════════════════════════════════════════
#  Provento
# ═══════════════════════════════════════════════════════════════════
class ProventoCreate(BaseModel):
    model_config = ConfigDict(strict=True)

    contribuinte_id: int
    data_pagamento: date
    tipo_provento: TipoProvento
    ticker: str = Field(..., min_length=1, max_length=20)
    cnpj_fonte: str | None = Field(default=None, max_length=18)
    valor_bruto: MonetaryBR
    irrf: MonetaryBR = Decimal("0.00")
    valor_liquido: MonetaryBR

    @field_validator("cnpj_fonte")
    @classmethod
    def _validar_cnpj(cls, v: str | None) -> str | None:
        if v is not None and not CNPJ_REGEX.match(v):
            raise ValueError("CNPJ deve estar no formato 00.000.000/0000-00")
        return v


class ProventoRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    contribuinte_id: int
    data_pagamento: date
    tipo_provento: str
    ticker: str
    cnpj_fonte: str | None
    valor_bruto: Decimal
    irrf: Decimal
    valor_liquido: Decimal
    created_at: datetime
    updated_at: datetime
