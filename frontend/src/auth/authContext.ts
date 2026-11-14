import { createContext } from 'react'
import type { CurrentUser } from '../api'

export interface AuthState {
  /** Usuario autenticado; `null` si es un lector anónimo. */
  user: CurrentUser | null
  /** Token JWT en memoria; `null` si no hay sesión. */
  token: string | null
  login: (username: string, password: string) => Promise<void>
  logout: () => void
}

export const AuthContext = createContext<AuthState | null>(null)
