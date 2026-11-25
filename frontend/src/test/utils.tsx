import { render, screen } from '@testing-library/react'
import type { ReactNode } from 'react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router'
import { vi } from 'vitest'
import type { CurrentUser, Role, TokenResponse } from '../api'
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

/**
 * Renderiza la aplicación completa en la ruta indicada. `extra` se renderiza
 * dentro del router (p. ej. un botón «atrás» o una sonda de la URL).
 */
export function renderApp(route = '/', extra?: ReactNode) {
  const user = userEvent.setup()
  const result = render(
    <AuthProvider>
      <MemoryRouter initialEntries={[route]}>
        <AppRoutes />
        {extra}
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

/** Respuestas de `POST /auth/token` y `GET /auth/me` para iniciar sesión con un rol. */
export function authRoutes(role: Role): Record<string, Handler> {
  return {
    '/auth/token': () => jsonResponse(tokenFixture({ role })),
    '/auth/me': () => jsonResponse(userFixture({ role })),
  }
}

/**
 * Renderiza la aplicación, inicia sesión desde el formulario (la sesión vive
 * en memoria) y vuelve a `route`, como hace el login con `state.from`. El
 * `fetch` tiene que incluir `authRoutes(role)`.
 */
export async function renderLoggedIn(route: string) {
  const user = userEvent.setup()
  const result = render(
    <AuthProvider>
      <MemoryRouter initialEntries={[{ pathname: '/login', state: { from: route } }]}>
        <AppRoutes />
      </MemoryRouter>
    </AuthProvider>,
  )
  await user.type(screen.getByLabelText('Usuario'), 'usuario-prueba')
  await user.type(screen.getByLabelText('Contraseña'), 'contrasena-prueba')
  await user.click(screen.getByRole('button', { name: 'Iniciar sesión' }))
  await screen.findByRole('button', { name: 'Cerrar sesión' })
  return { user, ...result }
}

/** Cuerpo JSON de la última llamada a `fetch` con ese método y ruta. */
export function lastBody(fetchMock: ReturnType<typeof mockFetch>, method: string, path: string): unknown {
  const call = fetchMock.mock.calls.filter(
    ([url, init]) => new URL(String(url)).pathname === path && (init?.method ?? 'GET') === method,
  ).at(-1)
  return call ? JSON.parse(String(call[1]?.body)) : undefined
}

/** Llamadas a `fetch` con ese método y ruta. */
export function callsTo(fetchMock: ReturnType<typeof mockFetch>, method: string, path: string) {
  return fetchMock.mock.calls.filter(
    ([url, init]) => new URL(String(url)).pathname === path && (init?.method ?? 'GET') === method,
  )
}
