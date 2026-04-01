"""
Interface Base para o Padrão Strategy de Parsers de Informe Bancário/Trabalho.

Cada banco ou tipo de informe tem sua própria subclasse concreta que sabe COMO
extrair dados. O resto do sistema não precisa saber qual estratégia está ativa.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from decimal import Decimal


# ─── Data Transfer Objects (compartilhados entre estratégias) ──────────────────

@dataclass
class RendimentoExtraido:
    """Um rendimento extraído do PDF."""
    categoria: str  # tributacao_exclusiva | isento | tributavel
    descricao: str
    valor: Decimal
    irrf: Decimal = Decimal("0.00")


@dataclass
class SaldoExtraido:
    """Saldo extraído do PDF."""
    tipo_conta: str  # corrente, poupanca, investimento, corretora
    ano: int
    valor: Decimal


@dataclass
class RendimentoTrabalhoExtraido:
    """Dados extraídos de holerite anual."""
    rendimento_tributavel: Decimal = Decimal("0.00")
    contribuicao_previdenciaria: Decimal = Decimal("0.00")
    irrf: Decimal = Decimal("0.00")


@dataclass
class DespesaMedicaExtraido:
    """Despesa Médica com CNPJ do Prestador."""
    cnpj_prestador: str
    razao_social_prestador: str
    valor_pago: Decimal


@dataclass
class InformeExtraido:
    """Resultado completo da extração de um PDF — independente da estratégia."""
    tipo_informe: str = "banco_corretora"
    cnpj_fonte: str | None = None
    razao_social: str | None = None
    ano_calendario: int | None = None
    rendimentos: list[RendimentoExtraido] = field(default_factory=list)
    saldos: list[SaldoExtraido] = field(default_factory=list)
    rendimento_trabalho: RendimentoTrabalhoExtraido | None = None
    despesas_medicas: list[DespesaMedicaExtraido] = field(default_factory=list)
    texto_bruto: str = ""
    erros: list[str] = field(default_factory=list)


# ─── Interface Base Abstrata (Strategy) ───────────────────────────────────────

class BankParserStrategy(ABC):
    """
    Contrato que toda estratégia de parsing deve implementar.

    Cada subclasse é responsável por saber COMO extrair dados de um layout
    específico (Nubank, Itaú, Bradesco, etc.). A fábrica (ParserFactory)
    decide QUAL estratégia instanciar com base no texto do PDF.
    """

    @property
    @abstractmethod
    def nome_instituicao(self) -> str:
        """Nome legível da instituição que esta estratégia suporta."""
        ...

    @abstractmethod
    def extract_cabecalho(self, text: str) -> tuple[str | None, str | None, int | None]:
        """
        Extrai informações do cabeçalho do informe.

        Returns:
            Tupla (cnpj_fonte, razao_social, ano_calendario).
            Retornar None nos campos que não foram encontrados.
        """
        ...

    @abstractmethod
    def extract_rendimentos(self, text: str) -> list[RendimentoExtraido]:
        """Extrai todos os rendimentos financeiros do texto."""
        ...

    @abstractmethod
    def extract_saldos(self, text: str) -> list[SaldoExtraido]:
        """Extrai saldos de 31/12 (anterior e atual)."""
        ...

    def extract_despesas_medicas(self, text: str) -> list[DespesaMedicaExtraido]:
        """
        Extrai despesas médicas (se aplicável ao tipo de informe).
        Implementação padrão: retorna lista vazia.
        Subclasses de holerite devem sobrescrever.
        """
        return []

    def extract_rendimento_trabalho(self, text: str) -> RendimentoTrabalhoExtraido | None:
        """
        Extrai dados de holerite (se aplicável).
        Implementação padrão: retorna None.
        Subclasses de holerite devem sobrescrever.
        """
        return None

    def parse(self, text: str) -> InformeExtraido:
        """
        Template Method: orquestra a extração usando os métodos abstratos.
        Não deve ser sobrescrito — é o 'esqueleto' do algoritmo.
        """
        result = InformeExtraido(texto_bruto=text)

        cnpj, razao, ano = self.extract_cabecalho(text)
        result.cnpj_fonte = cnpj
        result.razao_social = razao
        result.ano_calendario = ano

        if not cnpj:
            result.erros.append("CNPJ da fonte pagadora não encontrado")
        if not razao:
            result.erros.append("Razão Social não encontrada")
        if not ano:
            result.erros.append("Ano-calendário não encontrado")

        # Tenta extração de holerite
        work = self.extract_rendimento_trabalho(text)
        if work is not None:
            result.tipo_informe = "trabalho_assalariado"
            result.rendimento_trabalho = work
            result.despesas_medicas = self.extract_despesas_medicas(text)

            if work.rendimento_tributavel == Decimal("0.00"):
                result.erros.append(
                    "Holerite detectado, mas Salário 3.1 não foi lido com nitidez."
                )
        else:
            # Informe financeiro bancário
            result.rendimentos = self.extract_rendimentos(text)
            result.saldos = self.extract_saldos(text)

        return result
