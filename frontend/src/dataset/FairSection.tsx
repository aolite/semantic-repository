import { apiHref, type FairSummary } from '../api'
import { NOT_STATED, PLACEHOLDERS } from '../catalog/labels'
import {
  FAIR_DIMENSIONS,
  FAIR_ENGINE_PLACEHOLDER,
  FAIR_SCORE_NOTE,
  FAIR_STATUS_TEXT,
  fairDate,
  fairStatus,
  fairWidth,
} from './fair'

/**
 * Sección «Evaluación FAIR» de la ficha (prototipo, Ficha de dataset). Con
 * puntuaciones, muestra el total, el nivel de madurez de F-UJI y el desglose
 * por principio, sin las pistas de ejemplo del prototipo (contrato de la fase
 * 4, sección 6). Si la evaluación está en cola, en curso, ha fallado o no
 * existe, lo dice; si además hay puntuaciones (de la última evaluación
 * terminada), las sigue mostrando.
 */
export function FairSection({ fair, version }: { fair: FairSummary | null; version: string | null }) {
  const status = fairStatus(fair)
  const scored = fair !== null && fair.total !== null

  return (
    <section aria-labelledby="h-fair" className="panel fair">
      <div className="panel__head">
        <h2 id="h-fair" className="panel__title">
          Evaluación FAIR
        </h2>
        {version && <span className="panel__hint">v{version}</span>}
      </div>

      {status !== 'done' && <p className="fair__status">{FAIR_STATUS_TEXT[status]}</p>}
      {status === 'done' && !scored && <p className="muted">{NOT_STATED}</p>}

      {fair && scored && (
        <>
          <div className="fair__summary">
            <div className="fair__ring">
              <span className="fair__total">{fair.total}</span>
              <span className="fair__max">/ 100</span>
            </div>
            <div className="fair__level">
              <span className="fair__maturity">
                {/* Madurez de F-UJI tal cual, de 0 a 3 (decisión 46). */}
                {fair.maturity != null ? `Madurez ${fair.maturity} / 3` : NOT_STATED}
              </span>
              <span className="fair__note">{FAIR_SCORE_NOTE}</span>
            </div>
          </div>

          <ul className="fair__dims" aria-label="Puntuación por principio">
            {FAIR_DIMENSIONS.map((dim) => {
              const score = fair[dim.key]
              return (
                <li key={dim.key} className="fair__dim">
                  <div className="fair__dim-head">
                    <span className="fair__dim-label">{dim.label}</span>
                    <span className="mono fair__dim-score">{score ?? NOT_STATED}</span>
                  </div>
                  <div className="fair__bar" aria-hidden="true">
                    <div className="fair__bar-fill" style={{ width: fairWidth(score), background: dim.color }} />
                  </div>
                </li>
              )
            })}
          </ul>

          <div className="fair__footer">
            <span>
              Última evaluación:{' '}
              {fair.evaluated_at ? (
                <time dateTime={fair.evaluated_at}>{fairDate(fair.evaluated_at)}</time>
              ) : (
                PLACEHOLDERS.date
              )}{' '}
              · Evaluador: {fair.evaluator ?? FAIR_ENGINE_PLACEHOLDER}
            </span>
            {fair.report_url && (
              <a href={apiHref(fair.report_url)} className="fair__report">
                Ver informe completo de pruebas
              </a>
            )}
          </div>
        </>
      )}
    </section>
  )
}
