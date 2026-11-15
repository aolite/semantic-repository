/**
 * Respuestas ficticias de vocabularios y ontologías con la forma de los
 * esquemas del OpenAPI. Solo para pruebas: los textos y números son de prueba,
 * no datos del repositorio. Al estar tipadas, el build falla si se desalinean
 * de `src/api/types.ts`.
 */
import type {
  ConceptDetail,
  ConceptNode,
  OntologyDetail,
  SchemeDetail,
  VocabularyCard,
  VocabularyCounts,
  VocabularyPage,
} from '../api'

const BASE = 'http://uri.test/itot/'

export function vocabCardFixture(overrides: Partial<VocabularyCard> = {}): VocabularyCard {
  return {
    kind: 'own',
    slug: 'onto-prueba',
    uri: `${BASE}onto/onto-prueba`,
    rdf_type: 'owl:Ontology',
    title: 'Ontología de prueba',
    prefix: 'pru',
    namespace: `${BASE}onto/onto-prueba#`,
    description: 'Descripción de prueba de la ontología.',
    status: 'published',
    version: '1.2.0',
    metrics: { classes: 13, properties: 7 },
    concepts: null,
    synthetic: false,
    ...overrides,
  }
}

/** Una tarjeta de cada tipo. */
export function vocabCardsFixture(): VocabularyCard[] {
  return [
    vocabCardFixture(),
    vocabCardFixture({
      kind: 'external',
      slug: null,
      uri: 'https://externa.test/onto/',
      title: 'Ontología externa de prueba',
      prefix: 'ext',
      namespace: 'https://externa.test/onto/',
      description: null,
      status: 'referenced',
      version: null,
      metrics: null,
    }),
    vocabCardFixture({
      kind: 'skos_corp',
      slug: 'corp-prueba',
      uri: `${BASE}vocab/corp/corp-prueba`,
      rdf_type: 'skos:ConceptScheme',
      title: 'Esquema corporativo de prueba',
      prefix: 'ecp',
      namespace: `${BASE}vocab/corp/corp-prueba/`,
      status: 'draft',
      version: '0.3',
      metrics: null,
      concepts: 0,
      synthetic: true,
    }),
    vocabCardFixture({
      kind: 'skos_domain',
      slug: 'esq-prueba',
      uri: `${BASE}vocab/esq-prueba`,
      rdf_type: 'skos:ConceptScheme',
      title: 'Esquema de dominio de prueba',
      prefix: 'esq',
      namespace: `${BASE}vocab/esq-prueba/`,
      version: '1.0',
      metrics: null,
      concepts: 6,
      synthetic: true,
    }),
  ]
}

export function vocabPageFixture(
  items: VocabularyCard[] = vocabCardsFixture(),
  counts: VocabularyCounts = { own: 3, external: 2, skos_corp: 4, skos_domain: 5 },
): VocabularyPage {
  return { items, total: items.length, counts }
}

const ONTO = `${BASE}onto/onto-prueba`

export function ontologyFixture(overrides: Partial<OntologyDetail> = {}): OntologyDetail {
  return {
    slug: 'onto-prueba',
    uri: ONTO,
    kind: 'own',
    status: 'published',
    synthetic: false,
    title: 'Ontología de prueba',
    description: 'Descripción de prueba de la ontología.',
    metadata: {
      prefix: 'pru',
      namespace: `${ONTO}#`,
      title: 'Ontología de prueba',
      description: null,
      creators: [],
      contributors: [],
      publisher: { uri: null, label: 'Publicador de prueba' },
      license: null,
      rights: null,
      issued: null,
      modified: null,
      created: null,
    },
    versioning: {
      version: '1.2.0',
      version_iri: `${ONTO}/1.2.0`,
      current_version: '1.2.0',
      prior_version: { version_iri: `${ONTO}/1.1.0`, version: '1.1.0' },
      backward_compatible_with: [{ version_iri: `${ONTO}/1.1.0`, version: '1.1.0' }],
      history: ['1.2.0', '1.1.0', '1.0.0'].map((version, i) => ({
        version,
        version_iri: `${ONTO}/${version}`,
        notes: `Notas de prueba de la ${version}.`,
        issued: null,
        current: i === 0,
        described: true,
      })),
    },
    metrics: {
      classes: 13,
      object_properties: 5,
      data_properties: 2,
      annotation_properties: 1,
      individuals: 4,
      logical_axioms: 40,
      imports: 2,
      dl_expressivity: null,
    },
    profile: { name: 'OWL 2 DL', compatible: ['OWL 2 RL'], approximate: true },
    consistency: {
      reasoner: 'Razonador de prueba',
      consistent: true,
      unsatisfiable_classes: 0,
      unsatisfiable: [],
      detail: null,
      includes_imports: false,
    },
    documentation: {
      documented: 19,
      total: 20,
      percent: 95,
      classes_documented: 12,
      classes_total: 13,
      properties_documented: 7,
      properties_total: 7,
    },
    metrics_computed_at: null,
    metrics_tool: null,
    imports: [
      { uri: 'https://importada.test/onto/', title: 'Importada de prueba', prefix: 'imp', version: '3.0', known: true },
    ],
    alignments: [
      {
        target_ontology: 'https://alineada.test/onto#',
        title: 'Alineada de prueba',
        prefix: 'ali',
        relation: 'http://www.w3.org/2000/01/rdf-schema#subClassOf',
        scope: null,
        version: null,
        count: 2,
        mappings: [
          { source: `${ONTO}#ClaseA`, target: 'https://alineada.test/onto#X' },
          { source: `${ONTO}#ClaseB`, target: 'https://alineada.test/onto#Y' },
        ],
      },
    ],
    used_by_datasets: [
      {
        slug: 'dataset-prueba',
        uri: `${BASE}dataset/dataset-prueba`,
        title: 'Dataset de prueba',
        versions: [{ version: '2.1.0', uri: `${BASE}dataset/dataset-prueba/2.1.0`, conforms_to: `${ONTO}/1.2.0` }],
      },
    ],
    subjects: [
      {
        uri: `${BASE}vocab/esq-prueba`,
        type: 'scheme',
        label: 'Esquema de dominio de prueba',
        scheme: { uri: `${BASE}vocab/esq-prueba`, slug: 'esq-prueba', corp: false, label: 'Esquema de dominio de prueba' },
      },
      {
        uri: `${BASE}vocab/corp/corp-prueba`,
        type: 'scheme',
        label: 'Esquema corporativo de prueba',
        scheme: { uri: `${BASE}vocab/corp/corp-prueba`, slug: 'corp-prueba', corp: true, label: 'Esquema corporativo de prueba' },
      },
    ],
    ...overrides,
  }
}

const SCHEME = `${BASE}vocab/esq-prueba`

function node(slug: string, label: string, children: ConceptNode[] = [], top = false): ConceptNode {
  return { uri: `${SCHEME}/${slug}`, slug, label, top_concept: top, children }
}

/**
 * Árbol de prueba:
 * - Grupo A → Concepto A1, Concepto Á2 (→ Concepto A2X)
 * - Grupo B → Concepto B1
 */
export function treeFixture(): ConceptNode[] {
  return [
    node('grupo-a', 'Grupo A', [node('concepto-a1', 'Concepto A1'), node('concepto-a2', 'Concepto Á2', [node('concepto-a2x', 'Concepto A2X')])], true),
    node('grupo-b', 'Grupo B', [node('concepto-b1', 'Concepto B1')], true),
  ]
}

export function schemeFixture(overrides: Partial<SchemeDetail> = {}): SchemeDetail {
  return {
    slug: 'esq-prueba',
    corp: false,
    kind: 'skos_domain',
    uri: SCHEME,
    title: 'Esquema de dominio de prueba',
    description: 'Descripción de prueba del esquema.',
    prefix: 'esq',
    namespace: `${SCHEME}/`,
    version: '1.0',
    status: 'published',
    synthetic: false,
    domain: { slug: 'ot', uri: `${BASE}vocab/dominio/ot`, label: 'Dominio de prueba' },
    responsible: null,
    metadata: { creators: [], publisher: null, license: null, issued: null, modified: null },
    concept_count: 6,
    tree: treeFixture(),
    ...overrides,
  }
}

export function corpSchemeFixture(overrides: Partial<SchemeDetail> = {}): SchemeDetail {
  const uri = `${BASE}vocab/corp/corp-prueba`
  return schemeFixture({
    slug: 'corp-prueba',
    corp: true,
    kind: 'skos_corp',
    uri,
    title: 'Esquema corporativo de prueba',
    prefix: 'ecp',
    namespace: `${uri}/`,
    version: null,
    status: 'draft',
    domain: null,
    concept_count: 0,
    tree: [],
    ...overrides,
  })
}

export function conceptFixture(overrides: Partial<ConceptDetail> = {}): ConceptDetail {
  return {
    uri: `${SCHEME}/concepto-a1`,
    slug: 'concepto-a1',
    scheme: { uri: SCHEME, slug: 'esq-prueba', corp: false, label: 'Esquema de dominio de prueba' },
    pref_label: 'Concepto A1',
    pref_labels: [
      { value: 'Concept A1 (en)', lang: 'en' },
      { value: 'Concepto A1', lang: 'es' },
      { value: 'Concepte A1 (ca)', lang: 'ca' },
    ],
    alt_labels: [{ value: 'Alternativa A1', lang: 'es' }],
    definition: 'Definición de prueba del concepto A1.',
    definitions: [{ value: 'Definición de prueba del concepto A1.', lang: 'es' }],
    top_concept: false,
    broader: [{ uri: `${SCHEME}/grupo-a`, label: 'Grupo A', scheme: SCHEME }],
    narrower: [],
    related: [{ uri: `${SCHEME}/concepto-b1`, label: 'Concepto B1', scheme: SCHEME }],
    exact_match: [],
    close_match: [],
    used_by: {
      datasets: [
        {
          slug: 'dataset-prueba',
          uri: `${BASE}dataset/dataset-prueba`,
          title: 'Dataset de prueba',
          versions: [{ version: '2.1.0', uri: `${BASE}dataset/dataset-prueba/2.1.0`, conforms_to: null }],
        },
      ],
      ontologies: [{ slug: 'onto-prueba', uri: ONTO, title: 'Ontología de prueba', versions: ['1.2.0'] }],
    },
    ...overrides,
  }
}
