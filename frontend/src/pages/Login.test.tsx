// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import type { InternalAxiosRequestConfig } from 'axios'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { toast } from 'sonner'
import { api, setAuthToken } from '../api/client'
import { Login } from './Login'

vi.mock('../api/client', () => ({
  api: { post: vi.fn() },
  setAuthToken: vi.fn(),
}))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

beforeEach(() => {
  localStorage.clear()
  vi.clearAllMocks()
})

afterEach(() => {
  cleanup()
  localStorage.clear()
})

function renderLogin() {
  render(
    <MemoryRouter initialEntries={['/login']} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/" element={<div>Tableau de bord de test</div>} />
      </Routes>
    </MemoryRouter>,
  )
}

function fillLoginForm() {
  fireEvent.change(screen.getByPlaceholderText('admin@primevisionsolutions.tn'), {
    target: { value: 'user@example.test' },
  })
  const password = document.querySelector<HTMLInputElement>('input[type="password"]')
  if (!password) throw new Error('Password field not found')
  fireEvent.change(password, { target: { value: 'dummy-password' } })
  fireEvent.click(screen.getByRole('button', { name: 'Se connecter' }))
}

describe('Login', () => {
  it('stores the signed-in user and navigates after a successful login', async () => {
    const user = { id: 1, first_name: 'Test' }
    vi.mocked(api.post).mockResolvedValue({
      data: { access_token: 'test-token', user },
      status: 200,
      statusText: 'OK',
      headers: {},
      config: {} as InternalAxiosRequestConfig,
    })
    renderLogin()

    fillLoginForm()

    expect(await screen.findByText('Tableau de bord de test')).toBeTruthy()
    expect(api.post).toHaveBeenCalledWith('/auth/login-json', {
      email: 'user@example.test',
      password: 'dummy-password',
    })
    expect(setAuthToken).toHaveBeenCalledWith('test-token')
    expect(JSON.parse(localStorage.getItem('prime_user') || 'null')).toEqual(user)
  })

  it('shows an error and stays signed out when login fails', async () => {
    vi.mocked(api.post).mockRejectedValue({ response: { data: { detail: 'Connexion refusée' } } })
    renderLogin()

    fillLoginForm()

    await waitFor(() => expect(toast.error).toHaveBeenCalledWith('Connexion refusée'))
    expect(setAuthToken).not.toHaveBeenCalled()
    expect(localStorage.getItem('prime_user')).toBeNull()
    expect(screen.getByRole('button', { name: 'Se connecter' })).toBeTruthy()
  })
})
