import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { ConfirmDialog } from './ConfirmDialog'

function Harness({ onConfirm = () => {}, busy = false }: { onConfirm?: () => void; busy?: boolean }) {
  const [open, setOpen] = useState(false)
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>
        Abrir
      </button>
      {open && (
        <ConfirmDialog
          title="Título de prueba"
          confirmLabel="Confirmar de prueba"
          busy={busy}
          onConfirm={onConfirm}
          onCancel={() => setOpen(false)}
        >
          <p>Texto de prueba.</p>
        </ConfirmDialog>
      )}
    </>
  )
}

describe('ConfirmDialog', () => {
  it('es un diálogo modal con nombre y descripción, y el foco empieza en «Cancelar»', async () => {
    const user = userEvent.setup()
    render(<Harness />)
    await user.click(screen.getByRole('button', { name: 'Abrir' }))
    const dialog = screen.getByRole('dialog', { name: 'Título de prueba' })
    expect(dialog).toHaveAttribute('aria-modal', 'true')
    expect(dialog).toHaveAccessibleDescription('Texto de prueba.')
    expect(screen.getByRole('button', { name: 'Cancelar' })).toHaveFocus()
  })

  it('Escape y «Cancelar» lo cierran y devuelven el foco al control que lo abrió', async () => {
    const user = userEvent.setup()
    render(<Harness />)
    const opener = screen.getByRole('button', { name: 'Abrir' })
    await user.click(opener)
    await user.keyboard('{Escape}')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(opener).toHaveFocus()

    await user.click(opener)
    await user.click(screen.getByRole('button', { name: 'Cancelar' }))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(opener).toHaveFocus()
  })

  it('atrapa el foco con Tab y Mayús+Tab', async () => {
    const user = userEvent.setup()
    render(<Harness />)
    await user.click(screen.getByRole('button', { name: 'Abrir' }))
    await user.tab()
    expect(screen.getByRole('button', { name: 'Confirmar de prueba' })).toHaveFocus()
    await user.tab()
    expect(screen.getByRole('button', { name: 'Cancelar' })).toHaveFocus()
    await user.tab({ shift: true })
    expect(screen.getByRole('button', { name: 'Confirmar de prueba' })).toHaveFocus()
  })

  it('confirma con el botón; mientras está ocupado no confirma ni se cierra', async () => {
    const user = userEvent.setup()
    const onConfirm = vi.fn()
    const { rerender } = render(<Harness onConfirm={onConfirm} />)
    await user.click(screen.getByRole('button', { name: 'Abrir' }))
    await user.click(screen.getByRole('button', { name: 'Confirmar de prueba' }))
    expect(onConfirm).toHaveBeenCalledTimes(1)

    rerender(<Harness onConfirm={onConfirm} busy />)
    expect(screen.getByRole('button', { name: 'Confirmar de prueba' })).toHaveAttribute('aria-disabled', 'true')
    await user.click(screen.getByRole('button', { name: 'Confirmar de prueba' }))
    await user.keyboard('{Escape}')
    expect(onConfirm).toHaveBeenCalledTimes(1)
    expect(screen.getByRole('dialog')).toBeInTheDocument()
  })
})
