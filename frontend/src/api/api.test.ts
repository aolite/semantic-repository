import { describe, expect, it } from 'vitest'
import { jsonResponse, mockFetch } from '../test/utils'
import { ApiError, fetchCurrentUser, fetchHealth, requestToken } from '.'

describe('Módulo api', () => {
  it('requestToken envía username y password como form-urlencoded', async () => {
    const fetchMock = mockFetch({
      '/auth/token': () => jsonResponse({ access_token: 't', token_type: 'bearer' }),
    })

    await expect(requestToken('u', 'p')).resolves.toEqual({ access_token: 't', token_type: 'bearer' })

    const body = fetchMock.mock.calls[0][1]?.body as URLSearchParams
    expect(body.get('username')).toBe('u')
    expect(body.get('password')).toBe('p')
    expect(body.get('grant_type')).toBe('password')
  })

  it('fetchCurrentUser añade la cabecera Bearer', async () => {
    const fetchMock = mockFetch({
      '/auth/me': () => jsonResponse({ username: 'u', role: 'miembro' }),
    })

    await fetchCurrentUser('abc')

    expect(new Headers(fetchMock.mock.calls[0][1]?.headers).get('Authorization')).toBe('Bearer abc')
  })

  it('lanza ApiError con el código HTTP cuando la respuesta no es correcta', async () => {
    mockFetch({ '/health': () => jsonResponse({}, 503) })

    await expect(fetchHealth()).rejects.toMatchObject({ name: 'ApiError', status: 503 })
  })

  it('lanza ApiError con status 0 si no hay conexión', async () => {
    mockFetch({
      '/health': () => {
        throw new TypeError('Failed to fetch')
      },
    })

    const error = await fetchHealth().catch((e: unknown) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect((error as ApiError).status).toBe(0)
  })
})
