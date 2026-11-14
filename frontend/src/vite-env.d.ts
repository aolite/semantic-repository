/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** URL base de la API del backend (sin barra final obligatoria). */
  readonly VITE_API_BASE_URL?: string
  /** Base de las URIs persistentes; equivale a BASE_URI del backend. */
  readonly VITE_BASE_URI?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
