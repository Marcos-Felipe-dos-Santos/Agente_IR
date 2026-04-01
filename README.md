# 🛡️ Agent IR — Ferramenta Experimental de Análise Fiscal (Local-First)

> **⚠️ AVISO IMPORTANTE DE RESPONSABILIDADE E ESCOPO**
> Este é um **projeto acadêmico e pessoal** de Ciência da Computação, focado em explorar a interseção entre algoritmos determinísticos (cálculo de IR) e Inferência de IA Local (LLMs). 
> * **NÃO é um produto comercial ou SaaS.**
> * **NÃO substitui um contador profissional.** O motor tributário pode conter bugs e não cobre todos os cenários complexos da B3 (como day-trade, bonificações, subscrições ou FIIs).
> * **NÃO possui integração real com a Receita Federal.** O módulo de auditoria funciona através de importação manual de dados (arquivos mock/JSON), pois não há acesso direto à API do e-CAC.
> * O usuário é o único responsável por conferir os valores no Programa Gerador da DIRPF oficial.

O **Agent IR** é um experimento de contabilidade digital construído sob a premissa de privacidade total (Zero-Cloud). Ele processa arquivos e realiza análises preditivas utilizando modelos de linguagem pesados rodando exclusivamente na máquina do usuário.

> 🚨 **RISCO DE VAZAMENTO VIA CLOUD SYNC**
> Para garantir a premissa "Zero-Cloud", **NÃO instales** este projeto em pastas sincronizadas por serviços de backup automático (Google Drive, iCloud, OneDrive, Dropbox). Se o teu sistema operativo sincronizar o ficheiro SQLite (`data/irpf.db`), os teus dados financeiros estarão expostos na nuvem em texto claro.

---

## 🚀 Funcionalidades Atuais

* **Motor Determinístico (B3)**: Algoritmo em Python para cálculo de Preço Médio Ponderado e compensação de prejuízos intermensais focado no cenário básico de Swing Trade de Ações.
* **Parser de PDFs (Experimental)**: Extração de dados de notas de corretagem e informes de rendimentos via Regex. *(Atenção: Atualmente otimizado para layouts sintéticos/específicos. Pode falhar em PDFs reais de bancos devido à variação de formatação).*
* **Conselheiro Fiscal IA (Opcional)**: Integração com o Ollama (`deepseek-r1:14b`) para gerar insights fiscais. Requer hardware de alta performance.
* **Dossiê Analítico**: Geração de PDFs vetoriais via `ReportLab` com a memória de cálculo.

---

## 💻 Requisitos de Hardware e Setup

Devido à natureza *Local-First* e ao uso de IA Generativa profunda, este projeto **exige hardware entusiasta** para uma experiência fluida.

* **Recomendado para o Módulo de IA**: GPU Dedicada com **8GB a 16GB de VRAM** (ex: NVIDIA RTX 4060 Ti ou superior) e 32GB de RAM.
* *Nota: Rodar a IA apenas em CPU resultará em latências severas (5 a 15 minutos por requisição).*

### Stack Tecnológica
* **Back-End**: Python 3.10+, FastAPI (Assíncrono), SQLAlchemy.
* **Front-End**: React, Vite, Recharts.
* **IA Local**: Ollama.

### Como Executar (Ambiente de Desenvolvimento)

```bash
# 1. Back-End
python -m venv venv
source venv/bin/activate  # ou .\venv\Scripts\activate no Windows
pip install -r requirements.txt
python seed.py  # Atenção: Cria banco SQLite local (Não criptografado)
uvicorn app.main:app --reload --port 8000

# 2. Front-End (Em outro terminal)
cd frontend-agente
npm install
npm run dev

# 3. Motor de IA (Opcional)
# Certifique-se de ter o Ollama instalado e rodando:
ollama run deepseek-r1:14b