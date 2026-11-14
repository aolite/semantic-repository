import type { Role } from '../api'

/** Nombre visible de cada rol (Plan.md, decisiones técnicas de la fase 1). */
export const ROLE_LABELS: Record<Role, string> = {
  miembro: 'Miembro',
  editor: 'Editor',
  admin: 'Admin',
}
