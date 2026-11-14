import { render } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { vi } from 'vitest'
import type { CurrentUser, TokenResponse } from '../api'
import { AppRoutes } from '../App'
import { AuthProvider } from '../auth/AuthProvider'

/**
 * Respuestas ficticias con la forma de los esquemas `Token` y `UserRead` del
 * OpenAPI. Al estar tipadas, el build falla si se desalinean de `types.ts`.
 */
export function tokenFixture(overrides: Partial<TokenResponse> = {}): TokenResponse {
  return { access_token: 'token-de-prueba', token_type: 'bearer', expires_in: 3600, role: 'miembro', ...overrides }
}

export function userFixture(overrides: Partial<CurrentUser> = {}): CurrentUser {
  return {
    id: '00000000-0000-4000-8000-000000000000',
    username: 'usuario-prueba',
    role: 'miembro',
    is_active: true,
    created_at: '2000-01-01T00:00:00Z',
    updated_at: '2000-01-01T00:00:00Z',
    ...overrides,
  }
}

/** Renderiza la aplicación completa en la ruta indicada. */
export function renderApp(route = '/') {
  const user = userEvent.setup()
  const result = render(
    <AuthProvider>
      <MemoryRouter initialEntries={[route]}>
        <AppRoutes />
      </MemoryRouter>
    </AuthProvider>,
  )
  return { user, ...result }
}

export function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

type Handler = (url: string, init?: RequestInit) => Response | Promise<Response>

/** Sustituye `fetch` por un mock que enruta por ruta de la API. */
export function mockFetch(routes: Record<string, Handler>) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : input.toString()
    const path = new URL(url).pathname
    const handler = routes[path]
    if (!handler) return jsonResponse({ detail: 'Not Found' }, 404)
    return handler(url, init)
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}
