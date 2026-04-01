"""
Módulo de Integração de Inteligência Artificial Local (Ollama)
Foca em atuar como Conselheiro Fiscal, absorvendo a apuração matemática 
fria e identificando estratégias de elisão e restituição legal, operando 100% offline.
"""

import json
import logging
from pprint import pformat
import httpx
from typing import Dict, Any

from sqlalchemy.orm import Session
from app.models.entities import Contribuinte

logger = logging.getLogger(__name__)


# Prompt rigoroso instruindo a persona, regras e restrições.
SYSTEM_PROMPT = """Você é um Auditor e Consultor Tributário Brasileiro Sênior especializado no IRPF (Imposto de Renda Pessoa Física). Seu foco é encontrar ELISÃO FISCAL (estratégias legais para o cliente não pagar imposto que não deveria) baseado ESTRITAMENTE nos dados consolidados repassados no modelo matemático a seguir.

**MANDAMENTOS:**
1. A matemática recebida já está processada e é a ÚNICA fonte de verdade. Não conteste a base de cálculo.
2. Analise a saúde de deduções (Modelo Simplificado x Completo). Lembre-se que Saúde é dedução ilimitada, Educação até R$3.561,50.
3. Se houver Prejuízo transferido, lembre ativamente o investidor para puxar esse crédito à Ficha Renda Variável de janeiro do ano que vem.
4. Fique esperto caso o limite ISENTO do Swing Trade (>20k de vendas/mês) tenha sido rompido, focando na importância do Tax Loss Harvesting para o próximo ano.
5. Em casos de Criptoativos > R$ 35k, alerte sobre a necessidade do GCAP com multas de juros SELIC e moratórios se não pago no mês apurado.
6. A sua resposta DEVE ser **exclusivamente no formato Markdown estruturado**, contendo títulos com hash (`###`), tabelas quando necessário, e um tom altamente profissional e técnico. NADA de "Eis aqui sua análise", "Olá amigo", responda diretamente a estrutura como se fosse um laudo que sai da impressora.

**ESTRUTURA DE SAÍDA EXIGIDA:**
### 1. RESUMO EXECUTIVO DO ANO FISCAL (Destaque o cenário encontrado em poucas frases de impacto)
### 2. ESTRATÉGIAS RECOMENDADAS (Numere as táticas prioritárias para compensação e deduções no PGBL)
### 3. DIAGNÓSTICO DE PREJUÍZO (O que ele carrega para os meses/anos subsequentes)
### 4. RISCOS IDENTIFICADOS (Caso exista estouro de Swing Trade ou Criptoativo)"""


async def get_estrategias_fiscais(
    db: Session,
    contribuinte_id: int,
    ano_calendario: int,
    relatorio_apurado: Dict[str, Any],
    dados_manuais: Dict[str, Any],
    modelo_ollama: str = "deepseek-r1:14b",
) -> str:
    """
    Envia o sumário da tax_engine para avaliação qualitativa pela IA local via Ollama.
    Garante altíssima tolerância (15min timeout) visto que modelos maiores
    exigem heavy math processing no hardware do usuário.
    """
    
    # 1. Recuperar info básica do contribuinte para contextualização humanizada
    contrib = db.get(Contribuinte, contribuinte_id)
    nome_usuario = contrib.nome_completo if contrib else f"Investidor ID {contribuinte_id}"

    # 2. Montar o payload
    user_message = f"""
NOME DO CONTRIBUINTE: {nome_usuario}
ANO FISCAL DA APURAÇÃO: {ano_calendario}

JSON DA APURAÇÃO MATEMÁTICA CONSOLIDADA (TAX ENGINE B3 & CRIPTOATIVOS):
{json.dumps(relatorio_apurado, indent=2, ensure_ascii=False)}

DADOS MANUAIS DO INVESTIDOR (DEDUÇÕES PARA ESTUDO DO MODELO COMPLETO):
{json.dumps(dados_manuais, indent=2, ensure_ascii=False)}

Gere o Relatório de Estratégias Legais em formatação exigida pelo Sistema.
"""

    ollama_payload = {
        "model": modelo_ollama,
        "system": SYSTEM_PROMPT,
        "prompt": user_message,
        "stream": False,
        "options": {
            "temperature": 0.2, # Precisão técnica, quase determinístico
        }
    }

    try:
        # 3. Consumir Llm HTTP Call with extended Timeout Limits.
        # Timeout de 900 segundos = 15 minutos globais.
        timeout_config = httpx.Timeout(900.0)
        
        async with httpx.AsyncClient(timeout=timeout_config) as client:
            logger.info(f"Conectando ao Ollama (http://localhost:11434) [Modelo: {modelo_ollama}]...")
            response = await client.post(
                "http://localhost:11434/api/generate",
                json=ollama_payload,
            )
            
            # Se for 404, o modelo não está baixado. 5xx: engine falhou.
            response.raise_for_status()
            
            ollama_output = response.json()
            response_text = ollama_output.get("response", "Erro: Resposta vazia do Ollama.")
            return response_text
            
    except httpx.ConnectError:
        logger.error("Servidor Ollama Offline.")
        return "### ❌ Erro de Conexão no Conselheiro de IA\n\nNenhuma inferência foi realizada pois o motor Ollama (`http://localhost:11434`) está offline. Confirme se o serviço está sendo executado na máquina local."
    except httpx.HTTPStatusError as e:
        logger.error(f"Erro no Ollama: {e.response.status_code} - {e.response.text}")
        if e.response.status_code == 404:
             return f"### ❌ Modelo Incompatível\n\nO modelo especificado (`{modelo_ollama}`) não foi encontrado. Em seu terminal, execute: `ollama pull {modelo_ollama}`."
        return f"### ❌ Erro na API do Ollama\n\nFalha inesperada: {e.response.status_code}"
    except httpx.TimeoutException:
        logger.error("Timeout! Ollama engasgou por mais de 15 minutos.")
        return "### ⏳ Limite de Tempo Excedido\n\nA IA do Ollama não conseguiu completar a análise no tempo limite de 15 minutos. Caso seu hardware seja modesto, tente instanciar um modelo menor ou verifique travamentos do servidor Ollama."
    except Exception as e:
        logger.exception("Erro desconhecido ao chamar modelo analítico local.")
        return f"### ❌ Erro Critico de Inferência\n\n{str(e)}"

# ── 2. Auditor de Malha Fina (Contencioso) ──────────────────────────

async def gerar_defesa_malha_fina(
    db: Session,
    contribuinte_id: int,
    ano_calendario: int,
    relatorio_auditoria: Dict[str, Any],
    modelo_ollama: str = "deepseek-r1:14b",
) -> str:
    contrib = db.get(Contribuinte, contribuinte_id)
    nome_usuario = contrib.nome_completo if contrib else f"Investidor ID {contribuinte_id}"
    
    system_prompt = """Você é um Auditor Sênior de Contencioso Fiscal com vasta experiência de defesa no e-CAC da Receita Federal. O usuário lhe apresenta um JSON das 'Divergências da Malha Fina'. O sistema local dele reportou números X e o Dedo-Duro do Portal e-CAC reportou Y.
    
**MANDAMENTOS OBRIGATÓRIOS (SAÍDA STRICTAMENTE EM MARKDOWN):**
1. Analise cada Red Flag detalhada no JSON. Classifique a periculosidade do bloqueio da Restituição.
2. Dite o 'Próximo Passo Processual' prático: (Ex: "A empresa reportou menos IRRF, acione o RH hoje e exija a retificação da DIRF / eSocial", ou "A clínica não declarou seu D-Med, prepare os recibos timbrados com CPF do médico em PDF para subir via e-Defesa no portal GOV").
3. Se houver `risco_malha_fina_alto`: true, recomende NUNCA transmitir a declaração Completa antes de regularizar. Dê a opção da Retificação Posterior.
4. Resuma a estratégia em marcadores (bullet points). Zero conversinha, seja o mais formal e impositivo possível."""

    prompt = f"""NOME DO CONTRIBUINTE: {nome_usuario}\nANO: {ano_calendario}\n\nRELATÓRIO EXECUTIVO DE DIVERGÊNCIAS (MALHA FINA):\n{json.dumps(relatorio_auditoria, indent=2, ensure_ascii=False)}\n\nGere o Parecer Técnico para o Contencioso."""

    pay = { "model": modelo_ollama, "system": system_prompt, "prompt": prompt, "stream": False, "options": { "temperature": 0.1 } }

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(900.0)) as c:
            logger.info("Acessando Conselheiro de Malha Fina Local (Ollama)...")
            res = await c.post("http://localhost:11434/api/generate", json=pay)
            res.raise_for_status()
            return res.json().get("response", "Erro Vazio")
    except httpx.ConnectError:
        return "### ❌ Servidor Ollama Offline"
    except Exception as e:
        return f"### ❌ Falha no Processador LLM\n\n{str(e)}"

