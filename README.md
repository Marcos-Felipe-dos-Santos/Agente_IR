🛡️ Agent IR — Versão 1.0
Inteligência Artificial Local & Auditoria Fiscal Determinística
O Agent IR é um ecossistema de contabilidade digital desenvolvido por Marcos, estudante de Ciência da Computação, focado em privacidade absoluta e precisão fiscal para o IRPF (Ano-base 2024 / Exercício 2025). Ao contrário de soluções em nuvem, o Agent IR processa dados sensíveis (PDFs bancários, holerites e notas de corretagem) inteiramente em ambiente local.

O projeto une o rigor matemático do Python para cálculos tributários complexos com o raciocínio profundo de modelos de linguagem de larga escala (DeepSeek-R1) rodando localmente via Ollama.

🚀 Funcionalidades Principais
Motor de Renda Variável (B3): Cálculo automatizado de Preço Médio Ponderado, compensação de prejuízos intermensais e controle de isenção de R$ 20 mil para ações.

Radar de Criptoativos: Monitoramento do teto de isenção de R$ 35 mil para alienações de moedas digitais.

Parser de PDF com Regex: Extração inteligente de dados em Informes de Rendimentos Bancários e Holerites (Trabalho Assalariado), incluindo captura "gulosa" de despesas médicas e planos de saúde no Quadro 7.

Conselheiro Fiscal IA (Offline): Integração assíncrona com o Ollama (deepseek-r1:14b) para gerar estratégias de elisão fiscal e simulação entre Modelo Completo e Simplificado.

Auditor Anti-Malha Fina: Comparação automática entre os dados locais e a Declaração Pré-Preenchida da Receita Federal, apontando divergências em tempo real.

Análise de Variação Patrimonial: Verificação de consistência entre a renda líquida declarada e a evolução de bens e direitos entre 31/12/2023 e 31/12/2024.

Dossiê Executivo (PDF): Geração de relatório técnico via ReportLab, consolidando memória de cálculo, gráficos de evolução e o parecer da IA.

💻 Stack Tecnológica
Back-End (O Motor)
FastAPI: Framework assíncrono de alta performance.

SQLAlchemy: ORM para gestão de dados em SQLite local.

Httpx: Cliente HTTP assíncrono para comunicação com Ollama com timeout de 15 minutos.

Pdfplumber & Regex: Engenharia de extração de dados não estruturados em PDFs.

ReportLab: Geração de documentos PDF vetoriais em tempo real.

Front-End (A Interface)
React + Vite: Interface reativa e performática.

Recharts: Visualização de dados e evolução patrimonial.

Axios: Integração com a API local.

IA Local
Ollama: Orquestração de LLMs locais.

DeepSeek-R1 (14B/32B): Modelo utilizado para raciocínio lógico-fiscal.

🛠️ Como Executar
1. Pré-requisitos
Python 3.10+

Node.js & npm

Ollama instalado e rodando o modelo deepseek-r1:14b.

2. Configuração do Back-End
Bash
# Ativar ambiente virtual
.\venv\Scripts\activate

# Instalar dependências
pip install -r requirements.txt

# Inicializar o banco de dados (Seed)
python seed.py

# Iniciar o servidor
uvicorn app.main:app --reload --port 8000
3. Configuração do Front-End
Bash
cd frontend-agente
npm install
npm run dev
🔒 Compromisso com a Privacidade
Toda a arquitetura do Agent IR foi desenhada sob a premissa de que dados financeiros não devem sair da máquina do usuário.

Os PDFs são lidos em memória (Zero-Leak).

A IA roda offline via porta 11434.

O banco de dados SQLite é criptografado pelo próprio sistema de arquivos local.

⚖️ Isenção de Responsabilidade
Este é um projeto acadêmico e experimental desenvolvido para fins de estudo de Ciência da Computação. O Agent IR não substitui a orientação de um contador profissional ou a conferência manual dos dados no programa oficial da Receita Federal.
