import { screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { renderApp } from '../test/utils'

const LINKS = [
  { name: 'Catálogo', path: '/' },
  { name: 'Vocabularios', path: '/vocabularios' },
  { name: 'Consulta SPARQL', path: '/sparql' },
]

describe('Navegación lateral', () => {
  it('renderiza los enlaces principales con su destino', () => {
    renderApp('/')
    const nav = screen.getByRole('navigation', { name: 'Principal' })
    for (const { name, path } of LINKS) {
      expect(within(nav).getByRole('link', { name })).toHaveAttribute('href', path)
    }
  })

  it.each(LINKS)('marca solo "$name" con aria-current en $path', ({ name, path }) => {
    renderApp(path)
    const nav = screen.getByRole('navigation', { name: 'Principal' })
    for (const link of LINKS) {
      const element = within(nav).getByRole('link', { name: link.name })
      if (link.name === name) {
        expect(element).toHaveAttribute('aria-current', 'page')
      } else {
        expect(element).not.toHaveAttribute('aria-current')
      }
    }
  })

  it('muestra la página provisional de cada ruta sin datos', () => {
    renderApp('/sparql')
    expect(screen.getByRole('heading', { level: 1, name: 'Consulta SPARQL' })).toBeInTheDocument()
    expect(screen.getByText('Disponible en la fase 4')).toBeInTheDocument()
  })

  it('construye la URL SPARQL a partir de VITE_BASE_URI', () => {
    renderApp('/')
    expect(screen.getByText('http://uri.test/itot/sparql')).toBeInTheDocument()
  })

  it('ofrece iniciar sesión cuando el usuario es anónimo', () => {
    renderApp('/')
    expect(screen.getByRole('link', { name: 'Iniciar sesión' })).toHaveAttribute('href', '/login')
  })
})
