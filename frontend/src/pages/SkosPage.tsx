import { useCallback } from 'react'
import { Link, useParams, useSearchParams } from 'react-router'
import {
  fetchConcept,
  fetchScheme,
  listVocabularies,
  schemeRdfUrl,
  type ConceptDetail,
  type ConceptNode,
  type ConceptRef,
  type SchemeDetail,
  type VocabularyCard,
} from '../api'
import { DOMAINS, NOT_STATED } from '../catalog/labels'
import { ConceptTree } from '../components/ConceptTree'
import { DomainTag, KindTag, StatusTag, SyntheticTag, TypeTag } from '../components/Tags'
import { useApiLoad } from '../hooks/useApiLoad'
import {
  conceptsLabel,
  isLinkableIri,
  KINDS,
  langRank,
  prefixLabel,
  VOCAB_PLACEHOLDERS,
  versionLabel,
} from '../vocab/labels'
import { conceptRouteFromUri, ontologyRoute, schemeRoute } from '../vocab/routes'
import '../styles/dataset.css'
import '../styles/catalog.css'
import '../styles/vocab.css'

/** Primer concepto con slug del árbol (recorrido en profundidad). */
function firstSlug(nodes: ConceptNode[]): string | null {
  for (const node of nodes) {
    if (node.slug) return node.slug
    const child = firstSlug(node.children)
    if (child) return child
  }
  return null
}

/**
 * Pantalla «Navegador SKOS»: `/vocabularios/:slug` (esquemas de dominio) y
 * `/vocabularios/corp/:slug` (corporativos), con `?concepto=`.
 */
export function SkosPage({ corp }: { corp: boolean }) {
  const { slug = '' } = useParams()
  const [searchParams, setSearchParams] = useSearchParams()
  const concept = searchParams.get('concepto')

  const schemeLoader = useCallback((signal: AbortSignal) => fetchScheme(slug, corp, signal), [slug, corp])
  const { state, retry } = useApiLoad(schemeLoader)

  if (state.status === 'loading' || state.status === 'idle') {
    return (
      <p role="status" className="state">
        Cargando esquema…
      </p>
    )
  }

  if (state.status === 'not-found') {
    return (
      <div className="dataset">
        <Breadcrumbs corp={corp} slug={slug} />
        <h1 className="page-title">Esquema no encontrado</h1>
        <p className="muted">
          No existe ningún esquema de conceptos en esta dirección. <Link to="/vocabularios">Volver a Vocabularios</Link>
        </p>
      </div>
    )
  }

  if (state.status === 'error') {
    return (
      <div className="dataset">
        <Breadcrumbs corp={corp} slug={slug} />
        <div role="alert" className="state state--error">
          <p>No se ha podido cargar el esquema.</p>
          <button type="button" className="button button--secondary" onClick={retry}>
            Reintentar
          </button>
        </div>
      </div>
    )
  }

  const scheme = state.data
  const selected = concept ?? firstSlug(scheme.tree)

  return (
    <SchemeView
      scheme={scheme}
      selected={selected}
      onSelect={(next) => setSearchParams({ concepto: next })}
    />
  )
}

function Breadcrumbs({ corp, slug }: { corp: boolean; slug: string }) {
  return (
    <nav aria-label="Migas de pan" className="breadcrumbs">
      <Link to="/vocabularios">Vocabularios</Link>
      <span aria-hidden="true">/</span>
      <span>{corp ? KINDS.skos_corp.short : KINDS.skos_domain.short}</span>
      <span aria-hidden="true">/</span>
      <span aria-current="page">{slug}</span>
    </nav>
  )
}

interface SchemeViewProps {
  scheme: SchemeDetail
  selected: string | null
  onSelect: (slug: string) => void
}

function SchemeView({ scheme, selected, onSelect }: SchemeViewProps) {
  const prefix = prefixLabel(scheme.prefix)
  return (
    <div className="dataset">
      <Breadcrumbs corp={scheme.corp} slug={scheme.slug} />

      <header className="vocab-header">
        <div className="dataset__header">
          <div className="dataset__tags">
            <TypeTag>skos:ConceptScheme</TypeTag>
            <KindTag kind={scheme.kind} />
            {scheme.domain && <DomainTag slug={scheme.domain.slug} />}
            <StatusTag status={scheme.status} />
            {scheme.synthetic && <SyntheticTag label="Sintético" />}
            <span className="tag tag--version mono">{versionLabel(scheme.version)}</span>
          </div>
          <h1 className="page-title dataset__title">{scheme.title ?? scheme.slug}</h1>
          {(prefix || scheme.namespace) && (
            <span className="mono vocab-header__ns">
              {prefix && <span className="card__prefix">{prefix}</span>} {scheme.namespace}
            </span>
          )}
          {scheme.description && <p className="vocab-header__desc">{scheme.description}</p>}
          {scheme.corp && (
            <p className="vocab-header__meta">
              Responsable: {scheme.responsible ?? VOCAB_PLACEHOLDERS.responsible}
            </p>
          )}
        </div>
        <div className="vocab-header__actions">
          <a className="button button--outline" href={schemeRdfUrl(scheme.slug, scheme.corp, 'turtle')} download>
            Exportar Turtle
          </a>
        </div>
      </header>

      <div className="skos">
        <SchemeList current={scheme} />

        <section aria-labelledby="h-tree" className="panel skos__tree">
          <div className="panel__head">
            <h2 id="h-tree" className="panel__title skos__tree-title">
              Jerarquía de conceptos
            </h2>
            <span className="panel__hint">{conceptsLabel(scheme.concept_count)}</span>
          </div>
          <ConceptTree
            key={scheme.uri}
            nodes={scheme.tree}
            selected={selected}
            onSelect={onSelect}
            label={`Conceptos de ${scheme.title ?? scheme.slug}`}
          />
        </section>

        {selected ? (
          <ConceptPanel scheme={scheme} slug={selected} />
        ) : (
          <article className="panel skos__concept">
            <p className="muted">Este esquema no tiene conceptos que mostrar.</p>
          </article>
        )}
      </div>
    </div>
  )
}

/** Lista de esquemas («De dominio» y «Corporativos») a partir de `GET /vocabularies`. */
function SchemeList({ current }: { current: SchemeDetail }) {
  const loader = useCallback((signal: AbortSignal) => listVocabularies({}, signal), [])
  const { state } = useApiLoad(loader)

  const groups: { title: string; corp: boolean; items: VocabularyCard[] }[] =
    state.status === 'ok'
      ? [
          { title: 'De dominio', corp: false, items: state.data.items.filter((i) => i.kind === 'skos_domain') },
          { title: 'Corporativos', corp: true, items: state.data.items.filter((i) => i.kind === 'skos_corp') },
        ]
      : []

  return (
    <nav aria-label="Esquemas" className="skos__schemes">
      {state.status === 'loading' && <p className="muted small">Cargando esquemas…</p>}
      {(state.status === 'error' || state.status === 'not-found') && (
        <p className="muted small">No se ha podido cargar la lista de esquemas.</p>
      )}
      {groups
        .filter((g) => g.items.length > 0)
        .map((g) => (
          <div key={g.title} className="skos__scheme-group">
            <h2 className="skos__scheme-title">{g.title}</h2>
            <ul className="skos__scheme-list">
              {g.items.map((item) => {
                if (!item.slug) return null
                const isCurrent = item.slug === current.slug && g.corp === current.corp
                const kind = g.corp ? 'skos_corp' : 'skos_domain'
                // Color del dominio si el esquema lo tiene; si no, el del tipo de vocabulario.
                const swatch = item.domain ? DOMAINS[item.domain.slug].swatch : KINDS[kind].swatch
                return (
                  <li key={item.uri}>
                    <Link
                      to={schemeRoute(item.slug, g.corp)}
                      className="skos__scheme-link"
                      aria-current={isCurrent ? 'page' : undefined}
                    >
                      <span className="sidebar__swatch" style={{ background: swatch }} aria-hidden="true" />
                      {item.title ?? item.slug}
                    </Link>
                  </li>
                )
              })}
            </ul>
          </div>
        ))}
    </nav>
  )
}

function ConceptPanel({ scheme, slug }: { scheme: SchemeDetail; slug: string }) {
  const loader = useCallback(
    (signal: AbortSignal) => fetchConcept(scheme.slug, scheme.corp, slug, signal),
    [scheme.slug, scheme.corp, slug],
  )
  const { state, retry } = useApiLoad(loader)
  const titled = state.status === 'ok' || state.status === 'not-found'

  return (
    <article
      aria-labelledby={titled ? 'concepto-titulo' : undefined}
      aria-label={titled ? undefined : 'Concepto'}
      className="panel skos__concept"
      aria-busy={state.status === 'loading'}
    >
      {state.status === 'loading' && (
        <p role="status" className="muted">
          Cargando concepto…
        </p>
      )}
      {state.status === 'not-found' && (
        <>
          <h2 id="concepto-titulo" className="skos__concept-title">
            Concepto no encontrado
          </h2>
          <p className="muted">El concepto «{slug}» no existe en este esquema.</p>
        </>
      )}
      {state.status === 'error' && (
        <div role="alert" className="state state--error">
          <p>No se ha podido cargar el concepto.</p>
          <button type="button" className="button button--secondary" onClick={retry}>
            Reintentar
          </button>
        </div>
      )}
      {state.status === 'ok' && <ConceptView scheme={scheme} concept={state.data} />}
    </article>
  )
}

/** Concepto enlazado (broader, related): al navegador si su URI sigue el patrón. */
function ConceptLink({ concept }: { concept: ConceptRef }) {
  const to = conceptRouteFromUri(concept.uri)
  const label = concept.label ?? concept.uri
  return to ? (
    <Link to={to} className="pill pill--link">
      {label}
    </Link>
  ) : (
    <span className="pill">{label}</span>
  )
}

function ExternalIri({ iri }: { iri: string }) {
  return isLinkableIri(iri) ? (
    <a href={iri} rel="noopener noreferrer" className="mono small">
      {iri}
    </a>
  ) : (
    <span className="mono small">{iri}</span>
  )
}

function ConceptView({ scheme, concept: c }: { scheme: SchemeDetail; concept: ConceptDetail }) {
  const prefix = prefixLabel(scheme.prefix)
  const prefLabels = [...c.pref_labels].sort((a, b) => langRank(a.lang) - langRank(b.lang))
  const altLabels = [...c.alt_labels].sort((a, b) => langRank(a.lang) - langRank(b.lang))
  const mappings = [
    ...c.exact_match.map((iri) => ({ rel: 'skos:exactMatch', iri })),
    ...c.close_match.map((iri) => ({ rel: 'skos:closeMatch', iri })),
  ]
  const uses = [
    ...c.used_by.datasets.map((d) => ({
      key: `d-${d.uri}`,
      to: `/datasets/${encodeURIComponent(d.slug)}`,
      title: d.title ?? d.slug,
      rel: 'dcat:theme',
    })),
    ...c.used_by.ontologies.map((o) => ({
      key: `o-${o.uri}`,
      to: ontologyRoute(o.slug),
      title: o.title ?? o.slug,
      rel: 'owl:Ontology · dct:subject',
    })),
  ]

  return (
    <>
      <div className="skos__concept-head">
        <span className="mono panel__hint">
          skos:Concept · {prefix ?? ''}
          {c.slug}
        </span>
        <h2 id="concepto-titulo" className="skos__concept-title">
          {c.pref_label ?? c.slug}
        </h2>
        {c.definition && <p className="panel__text">{c.definition}</p>}
      </div>

      <dl className="fields fields--grid skos__fields">
        {prefLabels.length > 0 ? (
          prefLabels.map((l, i) => (
            <div key={`${l.lang ?? 'sin-idioma'}-${i}`}>
              <dt className="mono">skos:prefLabel{l.lang ? ` @${l.lang}` : ''}</dt>
              <dd lang={l.lang ?? undefined}>{l.value}</dd>
            </div>
          ))
        ) : (
          <div>
            <dt className="mono">skos:prefLabel</dt>
            <dd>{NOT_STATED}</dd>
          </div>
        )}
        <div>
          <dt className="mono">skos:altLabel</dt>
          <dd>
            {altLabels.length > 0
              ? altLabels.map((l, i) => (
                  <span key={`${l.value}-${i}`} lang={l.lang ?? undefined}>
                    {i > 0 ? ', ' : ''}
                    {l.value}
                    {l.lang ? <span className="muted small"> @{l.lang}</span> : null}
                  </span>
                ))
              : '—'}
          </dd>
        </div>
        <div>
          <dt className="mono">skos:broader</dt>
          <dd className="pills">
            {c.broader.length > 0 ? c.broader.map((b) => <ConceptLink key={b.uri} concept={b} />) : <span className="muted">—</span>}
          </dd>
        </div>
        <div>
          <dt className="mono">skos:related</dt>
          <dd className="pills">
            {c.related.length > 0 ? c.related.map((r) => <ConceptLink key={r.uri} concept={r} />) : <span className="muted">—</span>}
          </dd>
        </div>
        <div>
          <dt className="mono">Mapeos externos</dt>
          <dd>
            {mappings.length > 0 ? (
              <ul className="field-list">
                {mappings.map((m) => (
                  <li key={`${m.rel}-${m.iri}`}>
                    <span className="mono muted small">{m.rel}</span> <ExternalIri iri={m.iri} />
                  </li>
                ))}
              </ul>
            ) : (
              <span className="muted">Sin mapeos externos todavía</span>
            )}
          </dd>
        </div>
      </dl>

      <div className="skos__uses">
        <h3 className="skos__uses-title">Recursos que usan este concepto</h3>
        {uses.length > 0 ? (
          <ul className="link-list">
            {uses.map((u) => (
              <li key={u.key}>
                <Link to={u.to} className="link-row">
                  <span className="strong">{u.title}</span>
                  <span className="mono link-row__meta">{u.rel}</span>
                </Link>
              </li>
            ))}
          </ul>
        ) : (
          <p className="muted small">Ningún recurso del catálogo lo referencia todavía.</p>
        )}
      </div>
    </>
  )
}
