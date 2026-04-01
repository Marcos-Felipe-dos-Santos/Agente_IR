import axios from 'axios';

// Instância do Axios apontando para a API local (FastAPI)
const api = axios.create({
  baseURL: 'http://localhost:8000/api/v1',
  headers: {
    'Content-Type': 'application/json',
  },
});

/**
 * Envia o CSV da B3 para processamento.
 * @param {File} file Arquivo CSV
 * @param {number} contribuinteId ID do contribuinte (default 1)
 */
export const uploadB3 = async (file, contribuinteId = 1) => {
  const formData = new FormData();
  formData.append('file', file);

  const response = await api.post(`/upload/b3-csv?contribuinte_id=${contribuinteId}`, formData, {
    headers: {
      'Content-Type': 'multipart/form-data',
    },
  });
  return response.data;
};

/**
 * Envia o PDF de Informe de Rendimentos para extração.
 * @param {File} file Arquivo PDF
 * @param {number} contribuinteId ID do contribuinte (default 1)
 */
export const uploadInforme = async (file, contribuinteId = 1) => {
  const formData = new FormData();
  formData.append('file', file);

  const response = await api.post(`/upload/informe-pdf?contribuinte_id=${contribuinteId}`, formData, {
    headers: {
      'Content-Type': 'multipart/form-data',
    },
  });
  return response.data;
};

/**
 * Solicita a apuração fiscal e relatório anual completo.
 * @param {number} contribuinteId ID do contribuinte (default 1)
 * @param {number} ano Ano-calendário base para apuração (ex: 2024)
 */
export const getApuracao = async (contribuinteId = 1, ano = 2024) => {
  const response = await api.get(`/apuracao/relatorio-anual`, {
    params: {
      contribuinte_id: contribuinteId,
      ano: ano,
    },
  });
  return response.data;
};

/**
 * Solicita análises e estratégias do Conselheiro de Inteligência Artificial Local.
 * @param {Object} dadosApuracao JSON com os dados consolidados da `getApuracao`
 * @param {string} modelo Modelo do Ollama a ser testado (default: deepseek-r1:14b)
 */
export const gerarEstrategiasIA = async (dadosApuracao, modelo = 'deepseek-r1:14b') => {
  const payload = {
    contribuinte_id: dadosApuracao.contribuinte_id,
    ano_calendario: dadosApuracao.ano_calendario,
    relatorio_apurado: dadosApuracao,
    dados_manuais: {}, // Poderá ser plugado no UI futuramente
    modelo_ollama: modelo
  };

  const response = await api.post(`/estrategias-fiscais`, payload);
  return response.data; // Retorna a string Markdown
};

/**
 * Envia o json e a resposta textual pro backend gerar o dossie executivo em PDF streamado.
 * @param {number} contribuinteId 
 * @param {number} ano 
 * @param {string} parecerIA 
 */
export const baixarDossiePDF = async (contribuinteId, ano, parecerIA) => {
  const response = await api.post('/relatorios/dossie', {
    contribuinte_id: contribuinteId,
    ano: ano,
    parecer_ia: parecerIA
  }, {
    responseType: 'blob'
  });
  return response.data;
};

export const cruzarAuditoriaReceita = async (contribuinteId, ano, prePreenchidaJson) => {
  const response = await api.post(`/auditoria/cruzar?contribuinte_id=${contribuinteId}`, {
    cpf_contribuinte: prePreenchidaJson.cpf_contribuinte,
    ano_exercicio: ano,
    rendimentos_trabalho: prePreenchidaJson.rendimentos_trabalho || [],
    despesas_medicas: prePreenchidaJson.despesas_medicas || [],
    bens_e_direitos_contas: prePreenchidaJson.bens_e_direitos_contas || []
  });
  return response.data;
};

export const gerarDefesaIA = async (contribuinteId, ano, auditoriaJson, modelo = "deepseek-r1:14b") => {
  const response = await api.post(`/estrategias-fiscais/contencioso`, {
    contribuinte_id: contribuinteId,
    ano: ano,
    malha_fina_json: auditoriaJson,
    modelo: modelo
  });
  return response.data;
};

export default api;
