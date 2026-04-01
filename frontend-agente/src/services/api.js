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

export default api;
