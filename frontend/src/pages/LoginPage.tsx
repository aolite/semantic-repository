import { useState, type FormEvent } from 'react'
import { useLocation, useNavigate } from 'react-router'
import { ApiError } from '../api'
import { useAuth } from '../auth/useAuth'

function errorMessage(error: unknown): string {
  if (error instanceof ApiError && (error.status === 400 || error.status === 401)) {
    return 'Usuario o contraseña incorrectos.'
  }
  return 'No se ha podido iniciar sesión. Inténtalo de nuevo más tarde.'
}

export function LoginPage() {
  const { login } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  const from = (location.state as { from?: string } | null)?.from ?? '/'

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(null)
    if (!username.trim() || !password) {
      setError('Introduce el usuario y la contraseña.')
      return
    }
    setSubmitting(true)
    try {
      await login(username.trim(), password)
      navigate(from, { replace: true })
    } catch (err) {
      setError(errorMessage(err))
      setSubmitting(false)
    }
  }

  return (
    <>
      <h1 className="page-title">Iniciar sesión</h1>
      <form className="form" onSubmit={handleSubmit} noValidate aria-describedby={error ? 'login-error' : undefined}>
        {error && (
          <p id="login-error" role="alert" className="form__error">
            {error}
          </p>
        )}
        <div className="form__field">
          <label htmlFor="login-username">Usuario</label>
          <input
            id="login-username"
            name="username"
            type="text"
            autoComplete="username"
            required
            aria-invalid={error ? true : undefined}
            value={username}
            onChange={(e) => setUsername(e.target.value)}
          />
        </div>
        <div className="form__field">
          <label htmlFor="login-password">Contraseña</label>
          <input
            id="login-password"
            name="password"
            type="password"
            autoComplete="current-password"
            required
            aria-invalid={error ? true : undefined}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </div>
        <button type="submit" className="button button--primary" disabled={submitting}>
          {submitting ? 'Entrando…' : 'Iniciar sesión'}
        </button>
      </form>
    </>
  )
}
