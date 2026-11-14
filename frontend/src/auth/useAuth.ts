import { useContext } from 'react'
import { AuthContext, type AuthState } from './authContext'

export function useAuth(): AuthState {
  const context = useContext(AuthContext)
  if (!context) throw new Error('useAuth debe usarse dentro de <AuthProvider>.')
  return context
}
