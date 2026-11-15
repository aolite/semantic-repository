import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { DomainSlug, VocabularyKind, VocabularyStatus } from '../api'
import { DomainTag, KindTag, StatusTag } from './Tags'

describe('Etiquetas', () => {
  it('KindTag muestra las etiquetas del prototipo y «Esquema auxiliar»', () => {
    render(
      <>
        <KindTag kind="own" />
        <KindTag kind="skos_corp" />
        <KindTag kind="auxiliary" />
      </>,
    )
    expect(screen.getByText('Ontología propia')).toBeInTheDocument()
    expect(screen.getByText('SKOS corporativo')).toBeInTheDocument()
    expect(screen.getByText('Esquema auxiliar')).toBeInTheDocument()
  })

  it('no rompe con valores desconocidos del contrato: los muestra tal cual', () => {
    render(
      <>
        <KindTag kind={'tipo_nuevo' as VocabularyKind} />
        <KindTag kind={'constructor' as VocabularyKind} />
        <StatusTag status={'retirada' as VocabularyStatus} />
        <DomainTag slug={'xx' as DomainSlug} />
      </>,
    )
    expect(screen.getByText('tipo_nuevo')).toBeInTheDocument()
    expect(screen.getByText('constructor')).toBeInTheDocument()
    expect(screen.getByText('retirada')).toBeInTheDocument()
    expect(screen.getByText('xx')).toBeInTheDocument()
  })
})
