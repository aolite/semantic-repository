import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { describe, expect, it, vi } from 'vitest'
import { ErrorBoundary } from './ErrorBoundary'

function Broken(): never {
  throw new Error('fallo de prueba')
}

describe('ErrorBoundary', () => {
  it('muestra un mensaje accesible en lugar de una página en blanco', () => {
    // React y el propio boundary escriben el error en la consola: se silencia en la prueba.
    const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {})
    render(
      <MemoryRouter>
        <ErrorBoundary>
          <Broken />
        </ErrorBoundary>
      </MemoryRouter>,
    )
    expect(screen.getByRole('alert')).toHaveTextContent('No se ha podido mostrar esta pantalla.')
    expect(screen.getByRole('link', { name: 'Volver al catálogo' })).toHaveAttribute('href', '/')
    expect(consoleError).toHaveBeenCalled()
  })

  it('muestra el contenido si no hay errores', () => {
    render(
      <MemoryRouter>
        <ErrorBoundary>
          <p>Contenido de prueba</p>
        </ErrorBoundary>
      </MemoryRouter>,
    )
    expect(screen.getByText('Contenido de prueba')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })
})
