import { apiRequest } from './client'
import type { HealthResponse } from './types'

/** `GET /health`. */
export function fetchHealth(): Promise<HealthResponse> {
  return apiRequest<HealthResponse>('/health')
}
