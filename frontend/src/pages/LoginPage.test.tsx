import { screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { jsonResponse, mockFetch, renderApp } from '../test/utils'

// Credenciales ficticias de prueba: la API está mockeada.
const USERNAME = 'usuario-prueba'
const PASSWORD = 'clave-prueba'
const TOKEN = 'token-de-prueba'

function mockAuthApi() {
  return mockFetch({
    '/auth/token': (_url, init) => {
      const body = new URLSearchParams(String(init?.body))
      if (body.get('username') === USERNAME && body.get('password') === PASSWORD) {
        return jsonResponse({ access_token: TOKEN, token_type: 'bearer' })
      }
      return jsonResponse({ detail: 'Incorrect username or password' }, 401)
    },
    '/auth/me': (_url, init) => {
      const auth = new Headers(init?.headers).get('Authorization')
      if (auth !== `Bearer ${TOKEN}`) return jsonResponse({ detail: 'Unauthorized' }, 401)
      return jsonResponse({ username: USERNAME, role: 'editor' })
    },
  })
}

async function fillAndSubmit(user: ReturnType<typeof renderApp>['user'], username: string, password: string) {
  await user.type(screen.getByLabelText('Usuario'), username)
  await user.type(screen.getByLabelText('Contraseña'), password)
  await user.click(screen.getByRole('button', { name: 'Iniciar sesión' }))
}

describe('Login', () => {
  it('tiene campos etiquetados', () => {
    renderApp('/login')
    expect(screen.getByLabelText('Usuario')).toHaveAttribute('autocomplete', 'username')
    expect(screen.getByLabelText('Contraseña')).toHaveAttribute('type', 'password')
  })

  it('inicia sesión, envía el formulario OAuth2 y muestra usuario y rol', async () => {
    const fetchMock = mockAuthApi()
    const { user } = renderApp('/login')

    await fillAndSubmit(user, USERNAME, PASSWORD)

    expect(await screen.findByRole('heading', { level: 1, name: 'Catálogo' })).toBeInTheDocument()
    const nav = screen.getByRole('navigation', { name: 'Principal' })
    expect(within(nav).getByText(USERNAME)).toBeInTheDocument()
    expect(within(nav).getByText('Editor')).toBeInTheDocument()

    const [tokenUrl, tokenInit] = fetchMock.mock.calls[0]
    expect(String(tokenUrl)).toBe('http://api.test/auth/token')
    expect(tokenInit?.method).toBe('POST')
    expect(new Headers(tokenInit?.headers).get('Content-Type')).toBe('application/x-www-form-urlencoded')
    expect(String(fetchMock.mock.calls[1][0])).toBe('http://api.test/auth/me')
  })

  it('muestra un error con role="alert" si las credenciales son incorrectas', async () => {
    mockAuthApi()
    const { user } = renderApp('/login')

    await fillAndSubmit(user, USERNAME, 'otra-clave')

    expect(await screen.findByRole('alert')).toHaveTextContent('Usuario o contraseña incorrectos.')
    expect(screen.getByLabelText('Usuario')).toHaveAttribute('aria-invalid', 'true')
    expect(screen.getByRole('link', { name: 'Iniciar sesión' })).toBeInTheDocument()
  })

  it('muestra un error genérico si la API no responde', async () => {
    mockFetch({
      '/auth/token': () => {
        throw new TypeError('Failed to fetch')
      },
    })
    const { user } = renderApp('/login')

    await fillAndSubmit(user, USERNAME, PASSWORD)

    expect(await screen.findByRole('alert')).toHaveTextContent('No se ha podido iniciar sesión')
  })

  it('valida los campos vacíos sin llamar a la API', async () => {
    const fetchMock = mockAuthApi()
    const { user } = renderApp('/login')

    await user.click(screen.getByRole('button', { name: 'Iniciar sesión' }))

    expect(screen.getByRole('alert')).toHaveTextContent('Introduce el usuario y la contraseña.')
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('cierra la sesión y vuelve al estado anónimo', async () => {
    mockAuthApi()
    const { user } = renderApp('/login')
    await fillAndSubmit(user, USERNAME, PASSWORD)
    const nav = screen.getByRole('navigation', { name: 'Principal' })
    await within(nav).findByText(USERNAME)

    await user.click(within(nav).getByRole('button', { name: 'Cerrar sesión' }))

    expect(within(nav).queryByText(USERNAME)).not.toBeInTheDocument()
    expect(within(nav).queryByRole('button', { name: 'Cerrar sesión' })).not.toBeInTheDocument()
    expect(within(nav).getByRole('link', { name: 'Iniciar sesión' })).toBeInTheDocument()
  })
})
