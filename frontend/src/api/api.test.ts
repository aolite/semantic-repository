import { describe, expect, it } from 'vitest'
import { jsonResponse, mockFetch, tokenFixture, userFixture } from '../test/utils'
import { ApiError, fetchCurrentUser, fetchHealth, requestToken } from '.'

describe('Módulo api', () => {
  it('requestToken envía username y password como form-urlencoded', async () => {
    const token = tokenFixture({ access_token: 't', role: 'editor' })
    const fetchMock = mockFetch({
      '/auth/token': () => jsonResponse(token),
    })

    await expect(requestToken('u', 'p')).resolves.toEqual(token)

    const body = fetchMock.mock.calls[0][1]?.body as URLSearchParams
    expect(body.get('username')).toBe('u')
    expect(body.get('password')).toBe('p')
    expect(body.get('grant_type')).toBe('password')
  })

  it('fetchCurrentUser añade la cabecera Bearer y devuelve el UserRead', async () => {
    const me = userFixture()
    const fetchMock = mockFetch({
      '/auth/me': () => jsonResponse(me),
    })

    await expect(fetchCurrentUser('abc')).resolves.toEqual(me)

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
