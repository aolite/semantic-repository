import { useState } from 'react'

type CopyState = 'idle' | 'copied' | 'failed'

/** Botón «Copiar URI» con el resultado anunciado en una región `status`. */
export function CopyUriButton({ uri }: { uri: string }) {
  const [state, setState] = useState<CopyState>('idle')

  async function copy() {
    try {
      await navigator.clipboard.writeText(uri)
      setState('copied')
    } catch {
      setState('failed')
    }
  }

  return (
    <>
      <button type="button" className="button button--secondary" onClick={copy}>
        Copiar URI
      </button>
      <span role="status" className="dataset__copy-status">
        {state === 'copied' ? 'URI copiada' : state === 'failed' ? 'No se ha podido copiar la URI' : ''}
      </span>
    </>
  )
}
