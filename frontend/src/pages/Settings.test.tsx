// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import type { AxiosResponse } from 'axios'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { toast } from 'sonner'
import { api } from '../api/client'
import { Settings } from './Settings'

vi.mock('../api/client', () => ({
  api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn(), defaults: { baseURL: '/api/v1' } },
  clearAuth: vi.fn(),
}))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

const users = [
  { id: 1, first_name: 'Test', last_name: 'Admin', email: 'admin@example.com', role: 'admin', is_active: true },
  { id: 2, first_name: 'Test', last_name: 'Viewer', email: 'viewer@example.com', role: 'viewer', is_active: true },
]

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.setItem('prime_user', JSON.stringify({ id: 1, role: 'admin' }))
  vi.mocked(api.get).mockImplementation(async (url) => ({
    data: url === '/admin/company' ? { name: 'Test company' } : url === '/users' ? users : [],
  }) as AxiosResponse)
  vi.mocked(api.post).mockResolvedValue({ data: {} } as AxiosResponse)
})
afterEach(() => { cleanup(); localStorage.clear(); vi.restoreAllMocks() })

describe('security settings', () => {
  it('allows a non-admin to access password security even if company loading fails', async () => {
    localStorage.setItem('prime_user', JSON.stringify({ id: 2, role: 'viewer' }))
    vi.mocked(api.get).mockImplementation(async (url) => {
      if (url === '/admin/company') throw new Error('unavailable')
      return { data: [] } as AxiosResponse
    })
    render(<MemoryRouter><Settings /></MemoryRouter>)
    expect(await screen.findByRole('alert')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Sécurité du compte' }))
    expect(screen.getByLabelText('Mot de passe actuel')).toBeTruthy()
  })

  it('lets an admin revoke another account without offering that action for itself', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    render(<MemoryRouter><Settings /></MemoryRouter>)
    fireEvent.click(await screen.findByRole('button', { name: 'Utilisateurs (2)' }))
    const revokeButtons = screen.getAllByRole('button', { name: 'Déconnecter ses sessions' })
    expect(revokeButtons).toHaveLength(1)
    fireEvent.click(revokeButtons[0])
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/users/2/revoke-sessions'))
    expect(toast.success).toHaveBeenCalledWith('Toutes les sessions de cet utilisateur ont été déconnectées.')
  })

  it('does not show administrative revocation controls to a viewer', async () => {
    localStorage.setItem('prime_user', JSON.stringify({ id: 2, role: 'viewer' }))
    render(<MemoryRouter><Settings /></MemoryRouter>)
    fireEvent.click(await screen.findByRole('button', { name: 'Utilisateurs (2)' }))
    expect(screen.queryByRole('button', { name: 'Déconnecter ses sessions' })).toBeNull()
  })
})
