import { useCallback, useMemo, useState, type ReactNode } from 'react'
import { fetchCurrentUser, requestToken, type CurrentUser } from '../api'
import { AuthContext, type AuthState } from './authContext'

/**
 * Sesión del usuario.
 *
 * El token JWT se guarda solo en memoria (estado de React), no en
 * sessionStorage ni localStorage: así un script inyectado no puede leerlo
 * del almacenamiento del navegador ni sobrevive al cerrar la pestaña.
 * El coste es que recargar la página cierra la sesión.
 */
export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(null)
  const [user, setUser] = useState<CurrentUser | null>(null)

  const login = useCallback(async (username: string, password: string) => {
    const { access_token } = await requestToken(username, password)
    const me = await fetchCurrentUser(access_token)
    setToken(access_token)
    setUser(me)
  }, [])

  const logout = useCallback(() => {
    setToken(null)
    setUser(null)
  }, [])

  const value = useMemo<AuthState>(
    () => ({ token, user, login, logout }),
    [token, user, login, logout],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
