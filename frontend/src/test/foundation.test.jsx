import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import App from '../App.jsx';
import { publicPages } from '../app/router.jsx';
import api from '../services/api.js';

describe('Phase 1 route scaffold', () => {
  it.each([...publicPages, ['/citizen/dashboard', 'Citizen Dashboard'],
    ['/cmo/dashboard', 'CMO Dashboard'], ['/officer/dashboard', 'Officer Dashboard'],
    ['/missing', 'Page not found']])('renders %s with a prototype disclaimer', (path, title) => {
    render(<MemoryRouter initialEntries={[path]}><App /></MemoryRouter>);
    expect(screen.getByRole('heading', { name: title })).toBeInTheDocument();
    expect(screen.getByText(/not an official Government of Kerala service/)).toBeInTheDocument();
    expect(screen.getByText('Module under development.')).toBeInTheDocument();
  });

  it('configures the API client without authentication', () => {
    expect(api.defaults.baseURL).toBe(
      import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api/v1',
    );
    expect(api.defaults.timeout).toBe(10000);
    expect(api.defaults.headers.common.Authorization).toBeUndefined();
  });

  it('normalizes connection errors without discarding the original error', async () => {
    const failure = new Error('offline');
    await expect(api.get('/health', { adapter: () => Promise.reject(failure) }))
      .rejects.toMatchObject({ message: 'offline', userMessage: 'The service could not be reached.' });
  });
});

