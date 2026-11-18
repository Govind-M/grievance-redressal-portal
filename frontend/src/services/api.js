import axios from 'axios';

export const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api/v1',
  timeout: 10000,
  headers: { Accept: 'application/json' },
});

// Preserve the Axios error/cause and expose a stable user-facing message.
// Future auth configuration belongs here; no token handling exists in Phase 1.
api.interceptors.response.use(
  response => response,
  error => {
    error.userMessage = error.response
      ? 'The request could not be completed.'
      : 'The service could not be reached.';
    return Promise.reject(error);
  },
);

export default api;

