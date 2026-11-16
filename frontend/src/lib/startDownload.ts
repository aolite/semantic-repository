/**
 * Lanza la descarga de `url` con un enlace temporal, sin salir de la página
 * (la API responde con `Content-Disposition: attachment`). Está aparte para
 * poder sustituirlo en las pruebas: jsdom no navega.
 */
export function startDownload(url: string): void {
  const link = document.createElement('a')
  link.href = url
  link.rel = 'noopener'
  link.style.display = 'none'
  document.body.appendChild(link)
  link.click()
  link.remove()
}
