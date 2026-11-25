import type { Role } from '../api'

/** Nombre visible de cada rol (Plan.md, decisiones técnicas de la fase 1). */
export const ROLE_LABELS: Record<Role, string> = {
  miembro: 'Miembro',
  editor: 'Editor',
  admin: 'Admin',
}

/**
 * Crear, editar y dar de baja catálogos y datasets, y publicar versiones
 * (decisión 49): editor y admin (que hereda de editor). El miembro y el
 * lector anónimo no ven esos controles; el backend responde 403 y 401.
 */
export function canEdit(role: Role | null | undefined): boolean {
  return role === 'editor' || role === 'admin'
}
