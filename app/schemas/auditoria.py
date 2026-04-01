"""
Respostas da Auditoria de Cruzamento (Malha Fina).
"""

from typing import List, Optional
from pydantic import BaseModel, ConfigDict


class DivergenciaDTO(BaseModel):
    categoria: str          # "rendimentos", "saude", "bens"
    nome_item: str          # "Unimed Seguros", "Caixa Econômica..."
    valor_declarado_receita: str
    valor_apurado_sistema: str
    status: str             # "DIVERGENTE", "OK", "ALERTA"
    impacto_financeiro: str # Se gerou prejuízo pro utente ex: "- R$ 500,00"
    mensagem: str


class RelatorioAuditoria(BaseModel):
    model_config = ConfigDict(strict=False)

    contribuinte_id: int
    ano_exercicio: int
    divergencias: List[DivergenciaDTO]
    risco_malha_fina_alto: bool
    resumo_analise: str
