"""
Schemas para o Conselheiro Fiscal de IA (Ollama Local).
"""
from typing import Optional, Dict

from pydantic import BaseModel, Field


class AdvisorRequest(BaseModel):
    """Payload de entrada para gerar estratégias com o Ollama."""
    contribuinte_id: int = Field(..., description="ID do contribuinte para buscar seu contexto e nome")
    ano_calendario: int = Field(..., description="O ano base analisado")
    
    # Informações calculadas a serem consumidas
    relatorio_apurado: Dict = Field(..., description="O JSON matematicamente gerado pela tax_engine")
    
    # Informações extras que o usuário preencheu manualmente (saúde, instrução, dependentes)
    dados_manuais: Optional[Dict] = Field(
        default_factory=dict, 
        description="Dados extras para compor o modelo completo, ex: PGBL, saúde, INSS."
    )
    
    # Parâmetros customizados para o Ollama
    modelo_ollama: str = Field(
        default="deepseek-r1:14b",
        description="O modelo LLM local que será consumido na requisição."
    )
