import { Component, type ErrorInfo, type ReactNode } from 'react'
import { Link } from 'react-router'

interface Props {
  children: ReactNode
}

interface State {
  failed: boolean
}

/**
 * Captura los errores de renderizado de una pantalla y muestra un mensaje
 * accesible en lugar de una página en blanco. El Layout la monta con la ruta
 * como `key`, así que al navegar a otra pantalla se vuelve a intentar.
 */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { failed: false }

  static getDerivedStateFromError(): State {
    return { failed: true }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // Sin servicio de registro: queda en la consola del navegador.
    console.error('Error al mostrar la pantalla', error, info.componentStack)
  }

  render() {
    if (!this.state.failed) return this.props.children
    return (
      <div role="alert" className="state state--error">
        <p>No se ha podido mostrar esta pantalla.</p>
        <p>
          <Link to="/">Volver al catálogo</Link>
        </p>
      </div>
    )
  }
}
