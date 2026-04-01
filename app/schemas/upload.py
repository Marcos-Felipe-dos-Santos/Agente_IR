"""
Schemas para rotas de upload/importação de arquivos.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class PrecoMedioInfo(BaseModel):
    """Informações de preço médio por ticker."""
    preco_medio: str
    quantidade_em_carteira: str
    custo_total: str


class B3UploadResponse(BaseModel):
    """Resposta do endpoint de upload de CSV da B3."""
    model_config = ConfigDict(strict=False)

    status: str
    total_linhas_csv: int
    operacoes_inseridas: int
    operacoes_ignoradas: int
    desdobramentos_detectados: int
    erros: list[str]
    precos_medios: dict[str, PrecoMedioInfo]


# ═══════════════════════════════════════════════════════════════════
#  Informe de Rendimentos PDF
# ═══════════════════════════════════════════════════════════════════
class RendimentoDetalhe(BaseModel):
    """Detalhe de um rendimento extraído do PDF."""
    categoria: str
    descricao: str
    valor: str
    irrf: str


class SaldoDetalhe(BaseModel):
    """Detalhe de um saldo extraído do PDF."""
    tipo_conta: str
    ano: int
    valor: str


class RendimentoTrabalhoDetalhe(BaseModel):
    """Detalhe de rendimentos do trabalho assalariado."""
    rendimento_tributavel: str
    contribuicao_previdenciaria: str
    irrf: str


class DespesaMedicaDetalhe(BaseModel):
    """Detalhe de despesa médica do quadro 7."""
    cnpj_prestador: str
    nome_prestador: str
    valor_pago: str


class InformeUploadResponse(BaseModel):
    """Resposta do endpoint de upload de Informe de Rendimentos PDF."""
    model_config = ConfigDict(strict=False)

    status: str
    cnpj_fonte: str | None
    razao_social: str | None
    ano_calendario: int | None
    tipo_informe: str = "banco_corretora"
    rendimentos_inseridos: int
    saldos_atualizados: int
    erros: list[str]
    rendimentos: list[RendimentoDetalhe]
    saldos: list[SaldoDetalhe]
    
    rendimento_trabalho: RendimentoTrabalhoDetalhe | None = None
    despesas_medicas: list[DespesaMedicaDetalhe] | None = None
