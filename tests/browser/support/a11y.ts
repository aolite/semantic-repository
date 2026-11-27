import AxeBuilder from '@axe-core/playwright'
import { expect, type Page, type TestInfo } from '@playwright/test'

/**
 * Análisis de accesibilidad con axe-core (decisión 53).
 *
 * `expectNoSeriousA11yViolations` analiza la página tal como está (con el diálogo abierto, el menú
 * desplegado…) y falla con cualquier violación `serious` o `critical`. Las `moderate` y `minor` no
 * hacen fallar la prueba, pero se adjuntan a su informe (`axe-<nombre>.json`) para que se vean.
 *
 * No hay exclusiones por defecto. Una regla solo se puede desactivar con `disableRules`, y cada
 * una exige un `reason` que enlace con un hallazgo abierto (p. ej. `QA-51-02`): sin hallazgo, falla.
 */
export interface DisabledRule {
  rule: string
  /** Por qué se desactiva y qué hallazgo abierto lo cubre. */
  reason: string
}

const BLOCKING = ['serious', 'critical']

export interface A11yOptions {
  /** Selector de la parte a analizar; por defecto, toda la página. */
  include?: string
  disableRules?: DisabledRule[]
}

export async function expectNoSeriousA11yViolations(
  page: Page,
  testInfo: TestInfo,
  name: string,
  options: A11yOptions = {},
): Promise<void> {
  for (const disabled of options.disableRules ?? []) {
    if (!/QA-\d+-\d+/.test(disabled.reason)) {
      throw new Error(`La regla ${disabled.rule} se desactiva sin un hallazgo abierto (QA-NN-NN) en el motivo`)
    }
  }
  let builder = new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa', 'best-practice'])
  if (options.include) builder = builder.include(options.include)
  const disabled = (options.disableRules ?? []).map((d) => d.rule)
  if (disabled.length > 0) builder = builder.disableRules(disabled)
  const results = await builder.analyze()

  const summary = results.violations.map((v) => ({
    id: v.id,
    impact: v.impact,
    help: v.help,
    helpUrl: v.helpUrl,
    nodes: v.nodes.map((n) => ({ target: n.target, html: n.html.slice(0, 200), failure: n.failureSummary })),
  }))
  if (summary.length > 0) {
    await testInfo.attach(`axe-${name}.json`, { body: JSON.stringify(summary, null, 2), contentType: 'application/json' })
  }
  const blocking = results.violations.filter((v) => BLOCKING.includes(v.impact ?? ''))
  const text = blocking
    .map((v) => `${v.id} (${v.impact}): ${v.help}\n${v.nodes.map((n) => `    ${n.target.join(' ')}`).join('\n')}`)
    .join('\n')
  expect(blocking, `Violaciones serious o critical de axe en «${name}»:\n${text}`).toEqual([])
}
