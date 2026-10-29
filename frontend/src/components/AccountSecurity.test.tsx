// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import type { AxiosResponse } from 'axios'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { api, clearAuth } from '../api/client'
import { AccountSecurity } from './AccountSecurity'

vi.mock('../api/client', () => ({
  api: { post: vi.fn() },
  clearAuth: vi.fn(),
}))

function LoginResult() {
  const location = useLocation()
  return <div>{location.state?.authNotice?.text}</div>
}

function renderSecurity() {
  render(<MemoryRouter initialEntries={['/security']}><Routes>
    <Route path="/security" element={<AccountSecurity />} />
    <Route path="/login" element={<LoginResult />} />
  </Routes></MemoryRouter>)
}

function fill(current: string, next: string, confirmation = next) {
  fireEvent.change(screen.getByLabelText('Mot de passe actuel'), { target: { value: current } })
  fireEvent.change(screen.getByLabelText('Nouveau mot de passe'), { target: { value: next } })
  fireEvent.change(screen.getByLabelText('Confirmer le nouveau mot de passe'), { target: { value: confirmation } })
  fireEvent.click(screen.getByRole('button', { name: 'Modifier le mot de passe' }))
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(api.post).mockResolvedValue({ data: {} } as AxiosResponse)
})
afterEach(() => cleanup())

describe('account security', () => {
  it('validates confirmation and UTF-8 length without sending a request', () => {
    renderSecurity()
    fill('old-password-fictitious', 'valid-new-password-for-testing', 'different-password-for-testing')
    expect(screen.getByRole('alert').textContent).toContain('ne correspondent pas')
    expect(api.post).not.toHaveBeenCalled()
    fill('old-password-fictitious', 'é'.repeat(37))
    expect(screen.getByRole('alert').textContent).toContain('72 octets')
    expect(api.post).not.toHaveBeenCalled()
  })

  it('does not sign out for an incorrect current password', async () => {
    vi.mocked(api.post).mockRejectedValue({ response: { status: 400, data: { detail: 'Mot de passe actuel incorrect' } } })
    renderSecurity()
    fill('wrong-password-for-test', 'valid-new-password-for-testing')
    expect((await screen.findByRole('alert')).textContent).toBe('Mot de passe actuel incorrect')
    expect(clearAuth).not.toHaveBeenCalled()
    expect(screen.getByLabelText('Mot de passe actuel')).toBeTruthy()
  })

  it('clears auth and shows a persistent notice only after confirmed change', async () => {
    renderSecurity()
    fill('old-password-for-test', 'valid-new-password-for-testing')
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/auth/change-password', {
      old_password: 'old-password-for-test', new_password: 'valid-new-password-for-testing',
    }))
    expect(clearAuth).toHaveBeenCalledOnce()
    expect(await screen.findByText(/Toutes vos sessions ont été déconnectées/)).toBeTruthy()
  })

  it('reports an uncertain server outcome without claiming a successful change', async () => {
    vi.mocked(api.post).mockRejectedValue(new Error('offline'))
    renderSecurity()
    fill('old-password-for-test', 'valid-new-password-for-testing')
    expect((await screen.findByRole('alert')).textContent).toContain('Impossible de confirmer')
    expect(clearAuth).not.toHaveBeenCalled()
  })
})
