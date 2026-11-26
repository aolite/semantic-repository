/** Recuentos de las pantallas de catálogos (textos del frontend). */
export function datasetCount(n: number): string {
  return n === 1 ? '1 dataset' : `${n} datasets`
}

export function catalogCount(n: number): string {
  return n === 1 ? '1 catálogo' : `${n} catálogos`
}

export function schemeCount(n: number): string {
  return n === 1 ? '1 vocabulario' : `${n} vocabularios`
}

export function ontologyCount(n: number): string {
  return n === 1 ? '1 ontología' : `${n} ontologías`
}
