"""
Schemas que mapeiam o formato de importação Gov.br (e-CAC) da Pré-Preenchida.
Mockamos um JSON padronizado para representar as Declarações Oficiais da RFB.
"""

from typing import List, Optional
from pydantic import BaseModel, ConfigDict


class PrePreenchidaRendimento(BaseModel):
    cnpj_fonte: str
    nome_fonte: str
    rendimento_tributavel: str
    contribuicao_previdenciaria: str
    irrf_retido: str


class PrePreenchidaSaude(BaseModel):
    cnpj_prestador: str
    razao_social: str
    valor_pago: str


class PrePreenchidaBens(BaseModel):
    cnpj_instituicao: str | None = None
    banco: str
    saldo_31_12_anterior: str
    saldo_31_12_atual: str


class ReceitaPrePreenchidaUpload(BaseModel):
    """Payload JSON correspondente ao Dedo-duro da Receita Federal."""
    model_config = ConfigDict(strict=False)

    cpf_contribuinte: str
    ano_exercicio: int
    rendimentos_trabalho: List[PrePreenchidaRendimento] = []
    despesas_medicas: List[PrePreenchidaSaude] = []
    bens_e_direitos_contas: List[PrePreenchidaBens] = []
