"""
Modelos SQLAlchemy — entidades do domínio fiscal IRPF.

Todas as colunas monetárias usam Numeric(precision=15, scale=2) para evitar
erros de arredondamento com float. O SQLite armazena como TEXT internamente,
mas o SQLAlchemy converte de/para Decimal automaticamente.

Quantidades fracionárias (ações, cripto) usam Numeric(18, 8) para suportar
até 8 casas decimais.
"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


# ── Contribuinte ────────────────────────────────────────────────────
class Contribuinte(Base):
    """Dados pessoais do declarante."""

    __tablename__ = "contribuintes"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    cpf: Mapped[str] = mapped_column(String(14), unique=True, nullable=False)
    nome_completo: Mapped[str] = mapped_column(String(200), nullable=False)
    data_nascimento: Mapped[date] = mapped_column(nullable=False)
    titulo_eleitor: Mapped[str | None] = mapped_column(String(20))
    endereco: Mapped[str | None] = mapped_column(Text)
    ocupacao_principal: Mapped[str | None] = mapped_column(String(100))
    ano_exercicio: Mapped[int] = mapped_column(nullable=False)

    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # Relacionamentos
    contas: Mapped[list["ContaBancaria"]] = relationship(
        back_populates="contribuinte", cascade="all, delete-orphan"
    )
    operacoes_b3: Mapped[list["OperacaoB3"]] = relationship(
        back_populates="contribuinte", cascade="all, delete-orphan"
    )
    ativos_cripto: Mapped[list["AtivoCripto"]] = relationship(
        back_populates="contribuinte", cascade="all, delete-orphan"
    )
    proventos: Mapped[list["Provento"]] = relationship(
        back_populates="contribuinte", cascade="all, delete-orphan"
    )
    rendimentos_informe: Mapped[list["RendimentoInforme"]] = relationship(
        back_populates="contribuinte", cascade="all, delete-orphan"
    )
    rendimentos_trabalho: Mapped[list["RendimentoTrabalho"]] = relationship(
        back_populates="contribuinte", cascade="all, delete-orphan"
    )
    despesas_medicas: Mapped[list["DespesaMedica"]] = relationship(
        back_populates="contribuinte", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("cpf", "ano_exercicio", name="uq_cpf_ano"),
    )


# ── Conta Bancária ──────────────────────────────────────────────────
class ContaBancaria(Base):
    """
    Conta em banco ou corretora.
    Armazena saldos em 31/12 de cada ano para a declaração de bens.
    """

    __tablename__ = "contas_bancarias"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    contribuinte_id: Mapped[int] = mapped_column(
        ForeignKey("contribuintes.id", ondelete="CASCADE"), nullable=False
    )
    instituicao: Mapped[str] = mapped_column(String(100), nullable=False)
    codigo_banco: Mapped[str | None] = mapped_column(String(10))
    agencia: Mapped[str | None] = mapped_column(String(20))
    conta: Mapped[str | None] = mapped_column(String(30))
    tipo_conta: Mapped[str] = mapped_column(
        String(30), nullable=False
    )  # corrente, poupanca, investimento, corretora
    saldo_31_12_anterior: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), nullable=False, default=Decimal("0.00")
    )
    saldo_31_12_atual: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), nullable=False, default=Decimal("0.00")
    )
    ano_referencia: Mapped[int] = mapped_column(nullable=False)

    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        default=datetime.utcnow, onupdate=datetime.utcnow
    )

    contribuinte: Mapped["Contribuinte"] = relationship(back_populates="contas")

    __table_args__ = (
        CheckConstraint(
            "tipo_conta IN ('corrente','poupanca','investimento','corretora')",
            name="ck_tipo_conta",
        ),
    )


# ── Operação B3 (Bolsa) ────────────────────────────────────────────
class OperacaoB3(Base):
    """
    Cada linha representa uma compra ou venda de ativo em bolsa.
    Preço e quantidade são armazenados com 8 casas decimais para
    suportar frações (FIIs, ETFs com desdobramento etc.).
    """

    __tablename__ = "operacoes_b3"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    contribuinte_id: Mapped[int] = mapped_column(
        ForeignKey("contribuintes.id", ondelete="CASCADE"), nullable=False
    )
    data_operacao: Mapped[date] = mapped_column(nullable=False)
    tipo_operacao: Mapped[str] = mapped_column(
        String(10), nullable=False
    )  # compra | venda
    ticker: Mapped[str] = mapped_column(String(20), nullable=False)
    quantidade: Mapped[Decimal] = mapped_column(
        Numeric(18, 8), nullable=False
    )
    preco_unitario: Mapped[Decimal] = mapped_column(
        Numeric(18, 8), nullable=False
    )
    valor_total: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), nullable=False
    )
    custos_operacionais: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), nullable=False, default=Decimal("0.00")
    )
    nota_corretagem: Mapped[str | None] = mapped_column(String(50))
    corretora: Mapped[str | None] = mapped_column(String(100))

    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        default=datetime.utcnow, onupdate=datetime.utcnow
    )

    contribuinte: Mapped["Contribuinte"] = relationship(back_populates="operacoes_b3")

    __table_args__ = (
        CheckConstraint(
            "tipo_operacao IN ('compra','venda')", name="ck_tipo_operacao_b3"
        ),
        CheckConstraint("quantidade > 0", name="ck_quantidade_positiva"),
        CheckConstraint("preco_unitario >= 0", name="ck_preco_nao_negativo"),
    )


# ── Ativo Cripto ────────────────────────────────────────────────────
class AtivoCripto(Base):
    """
    Registro de compras/vendas de criptomoedas.
    A Receita Federal exige declaração de vendas cujo total mensal
    ultrapasse R$ 35.000,00 (isenção). Campos auxiliam nessa auditoria.
    """

    __tablename__ = "ativos_cripto"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    contribuinte_id: Mapped[int] = mapped_column(
        ForeignKey("contribuintes.id", ondelete="CASCADE"), nullable=False
    )
    data_operacao: Mapped[date] = mapped_column(nullable=False)
    tipo_operacao: Mapped[str] = mapped_column(
        String(10), nullable=False
    )  # compra | venda
    moeda: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # BTC, ETH, SOL…
    quantidade: Mapped[Decimal] = mapped_column(
        Numeric(18, 8), nullable=False
    )
    preco_unitario_brl: Mapped[Decimal] = mapped_column(
        Numeric(18, 8), nullable=False
    )
    valor_total_brl: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), nullable=False
    )
    exchange: Mapped[str | None] = mapped_column(String(100))
    custo_aquisicao_medio: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 8)
    )

    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        default=datetime.utcnow, onupdate=datetime.utcnow
    )

    contribuinte: Mapped["Contribuinte"] = relationship(back_populates="ativos_cripto")

    __table_args__ = (
        CheckConstraint(
            "tipo_operacao IN ('compra','venda')", name="ck_tipo_operacao_cripto"
        ),
        CheckConstraint("quantidade > 0", name="ck_qtd_cripto_positiva"),
    )


# ── Provento (Dividendos / JCP) ────────────────────────────────────
class Provento(Base):
    """
    Dividendos (isentos) e Juros sobre Capital Próprio (tributados na fonte).
    """

    __tablename__ = "proventos"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    contribuinte_id: Mapped[int] = mapped_column(
        ForeignKey("contribuintes.id", ondelete="CASCADE"), nullable=False
    )
    data_pagamento: Mapped[date] = mapped_column(nullable=False)
    tipo_provento: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # dividendo | jcp
    ticker: Mapped[str] = mapped_column(String(20), nullable=False)
    cnpj_fonte: Mapped[str | None] = mapped_column(String(18))
    valor_bruto: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), nullable=False
    )
    irrf: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), nullable=False, default=Decimal("0.00")
    )
    valor_liquido: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), nullable=False
    )

    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        default=datetime.utcnow, onupdate=datetime.utcnow
    )

    contribuinte: Mapped["Contribuinte"] = relationship(back_populates="proventos")

    __table_args__ = (
        CheckConstraint(
            "tipo_provento IN ('dividendo','jcp')", name="ck_tipo_provento"
        ),
        CheckConstraint("valor_bruto >= 0", name="ck_provento_positivo"),
    )


# ── Rendimento de Informe Bancário ──────────────────────────────────
class RendimentoInforme(Base):
    """
    Rendimentos extraídos de PDFs de Informe de Rendimentos Financeiros
    emitidos por bancos e corretoras.
    Categorias:
      - tributacao_exclusiva: CDB, RDB, Fundos (tributados na fonte)
      - isento: LCI, LCA, Poupança, Dividendos
      - tributavel: rendimentos sujeitos ao ajuste anual
    """

    __tablename__ = "rendimentos_informe"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    contribuinte_id: Mapped[int] = mapped_column(
        ForeignKey("contribuintes.id", ondelete="CASCADE"), nullable=False
    )
    cnpj_fonte: Mapped[str] = mapped_column(String(18), nullable=False)
    razao_social_fonte: Mapped[str] = mapped_column(String(200), nullable=False)
    ano_calendario: Mapped[int] = mapped_column(nullable=False)
    categoria: Mapped[str] = mapped_column(
        String(30), nullable=False
    )  # tributacao_exclusiva | isento | tributavel
    descricao: Mapped[str] = mapped_column(Text, nullable=False)
    valor: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), nullable=False
    )
    irrf: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), nullable=False, default=Decimal("0.00")
    )

    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        default=datetime.utcnow, onupdate=datetime.utcnow
    )

    contribuinte: Mapped["Contribuinte"] = relationship(
        back_populates="rendimentos_informe"
    )

    __table_args__ = (
        CheckConstraint(
            "categoria IN ('tributacao_exclusiva','isento','tributavel')",
            name="ck_categoria_rendimento",
        ),
        CheckConstraint("valor >= 0", name="ck_valor_rendimento_positivo"),
    )


# ── Rendimento de Trabalho Assalariado ──────────────────────────────
class RendimentoTrabalho(Base):
    """
    Rendimentos do Trabalho Assalariado.
    Extraído de Informes de Rendimento do tipo holerite.
    """

    __tablename__ = "rendimentos_trabalho"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    contribuinte_id: Mapped[int] = mapped_column(
        ForeignKey("contribuintes.id", ondelete="CASCADE"), nullable=False
    )
    cnpj_fonte: Mapped[str] = mapped_column(String(18), nullable=False)
    razao_social_fonte: Mapped[str] = mapped_column(String(200), nullable=False)
    ano_calendario: Mapped[int] = mapped_column(nullable=False)
    
    rendimento_tributavel: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), nullable=False, default=Decimal("0.00")
    )
    contribuicao_previdenciaria: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), nullable=False, default=Decimal("0.00")
    )
    irrf: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), nullable=False, default=Decimal("0.00")
    )

    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        default=datetime.utcnow, onupdate=datetime.utcnow
    )

    contribuinte: Mapped["Contribuinte"] = relationship(
        back_populates="rendimentos_trabalho"
    )


# ── Despesas Médicas (Instrução/Saúde) ─────────────────────────────
class DespesaMedica(Base):
    """
    Despesas médicas ou de saúde reportadas em 'Informações Complementares'.
    """

    __tablename__ = "despesas_medicas"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    contribuinte_id: Mapped[int] = mapped_column(
        ForeignKey("contribuintes.id", ondelete="CASCADE"), nullable=False
    )
    cnpj_prestador: Mapped[str] = mapped_column(String(18), nullable=False)
    razao_social_prestador: Mapped[str] = mapped_column(String(200), nullable=False)
    ano_calendario: Mapped[int] = mapped_column(nullable=False)
    
    valor_pago: Mapped[Decimal] = mapped_column(
        Numeric(15, 2), nullable=False
    )

    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        default=datetime.utcnow, onupdate=datetime.utcnow
    )

    contribuinte: Mapped["Contribuinte"] = relationship(
        back_populates="despesas_medicas"
    )
