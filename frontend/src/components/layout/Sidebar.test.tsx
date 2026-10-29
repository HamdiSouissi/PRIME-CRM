// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import type { AxiosResponse } from 'axios'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { api, clearAuth } from '../../api/client'
import { Sidebar } from './Sidebar'

vi.mock('../../api/client', () => ({
  api: { post: vi.fn() },
  clearAuth: vi.fn(() => { localStorage.removeItem('prime_token'); localStorage.removeItem('prime_user') }),
}))

function LoginResult() {
  const location = useLocation()
  return <div>{location.state?.authNotice?.text}</div>
}

function renderSidebar() {
  render(<MemoryRouter initialEntries={['/']}><Routes>
    <Route path="/" element={<Sidebar />} />
    <Route path="/login" element={<LoginResult />} />
  </Routes></MemoryRouter>)
}

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.setItem('prime_token', 'fictitious-token')
  localStorage.setItem('prime_user', JSON.stringify({ id: 1, first_name: 'Test', last_name: 'User' }))
  vi.mocked(api.post).mockResolvedValue({ data: {}, status: 200 } as AxiosResponse)
})
afterEach(() => { cleanup(); localStorage.clear() })

describe('logout everywhere', () => {
  it('calls the server, clears local authentication and confirms global revocation', async () => {
    renderSidebar()
    fireEvent.click(screen.getByRole('button', { name: 'Déconnexion partout' }))
    await waitFor(() => expect(api.post).toHaveBeenCalledWith('/auth/logout-all', undefined, expect.objectContaining({ validateStatus: expect.any(Function) })))
    expect(clearAuth).toHaveBeenCalledOnce()
    expect(localStorage.getItem('prime_token')).toBeNull()
    expect(await screen.findByText('Toutes vos sessions ont été déconnectées.')).toBeTruthy()
  })

  it('warns when the current token is invalid and other sessions cannot be confirmed', async () => {
    vi.mocked(api.post).mockResolvedValue({ data: {}, status: 401 } as AxiosResponse)
    renderSidebar()
    fireEvent.click(screen.getByRole('button', { name: 'Déconnexion partout' }))
    expect(await screen.findByText(/révocation des autres sessions n’a pas pu être confirmée/)).toBeTruthy()
    expect(clearAuth).toHaveBeenCalledOnce()
    const options = vi.mocked(api.post).mock.calls[0][2]
    expect(options?.validateStatus?.(401)).toBe(true)
    expect(options?.validateStatus?.(503)).toBe(false)
  })

  it('clears this browser but explicitly warns when server revocation cannot be confirmed', async () => {
    vi.mocked(api.post).mockRejectedValue(new Error('offline'))
    renderSidebar()
    fireEvent.click(screen.getByRole('button', { name: 'Déconnexion partout' }))
    expect(await screen.findByText(/révocation des autres sessions n’a pas pu être confirmée/)).toBeTruthy()
    expect(clearAuth).toHaveBeenCalledOnce()
    expect(localStorage.getItem('prime_token')).toBeNull()
  })
})
