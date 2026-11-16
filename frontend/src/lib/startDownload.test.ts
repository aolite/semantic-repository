import { describe, expect, it, vi } from 'vitest'
import { startDownload } from './startDownload'

describe('startDownload', () => {
  it('pulsa un enlace temporal a la URL y lo retira', () => {
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
      expect(this.href).toBe('http://api.test/dataset/x/1.0.0/a/fichero?token=t')
      expect(this.rel).toBe('noopener')
      expect(document.body.contains(this)).toBe(true)
    })
    startDownload('http://api.test/dataset/x/1.0.0/a/fichero?token=t')
    expect(click).toHaveBeenCalledTimes(1)
    expect(document.querySelector('a')).toBeNull()
  })
})
