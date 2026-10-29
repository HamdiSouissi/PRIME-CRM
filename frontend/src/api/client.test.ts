// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { InternalAxiosRequestConfig } from 'axios'
import { api, clearAuth, setAuthToken } from './client'

function successfulAdapter() {
  // A local Axios adapter keeps these tests independent of any backend.
  return vi.fn(async (config: InternalAxiosRequestConfig) => ({
    config,
    data: { ok: true },
    headers: {},
    status: 200,
    statusText: 'OK',
  }))
}

beforeEach(() => {
  clearAuth()
  localStorage.clear()
  // Avoid navigating away when the response interceptor sees a 401.
  window.history.replaceState({}, '', '/login')
})

afterEach(() => {
  clearAuth()
  localStorage.clear()
})

describe('API authentication', () => {
  it('stores the token and configures the authorization header', () => {
    setAuthToken('test-token')

    expect(localStorage.getItem('prime_token')).toBe('test-token')
    expect(api.defaults.headers.common.Authorization).toBe('Bearer test-token')
  })

  it('removes the stored identity and authorization header on logout', () => {
    setAuthToken('test-token')
    localStorage.setItem('prime_user', '{"id":1}')
    localStorage.setItem('unrelated', 'preserved')

    clearAuth()

    expect(localStorage.getItem('prime_token')).toBeNull()
    expect(localStorage.getItem('prime_user')).toBeNull()
    expect(localStorage.getItem('unrelated')).toBe('preserved')
    expect(api.defaults.headers.common.Authorization).toBeUndefined()
  })

  it('adds a persisted token to an outgoing request', async () => {
    localStorage.setItem('prime_token', 'persisted-token')
    const adapter = successfulAdapter()

    await api.get('/test', { adapter })

    expect(adapter).toHaveBeenCalledOnce()
    expect(adapter.mock.calls[0][0].headers.get('Authorization')).toBe('Bearer persisted-token')
  })

  it('does not add an authorization header when signed out', async () => {
    const adapter = successfulAdapter()

    await api.get('/test', { adapter })

    expect(adapter.mock.calls[0][0].headers.has('Authorization')).toBe(false)
  })

  it('does not resend an in-memory default token after another tab signs out', async () => {
    setAuthToken('old-token')
    localStorage.removeItem('prime_token')
    const adapter = successfulAdapter()

    await api.get('/test', { adapter })

    expect(adapter.mock.calls[0][0].headers.has('Authorization')).toBe(false)
  })

  it('keeps the session when the current password is wrong (400)', async () => {
    setAuthToken('valid-token')
    localStorage.setItem('prime_user', '{"id":1}')
    const error = { response: { status: 400, data: { detail: 'Mot de passe actuel incorrect' } } }
    const adapter = vi.fn().mockRejectedValue(error)

    await expect(api.post('/auth/change-password', {}, { adapter })).rejects.toBe(error)

    expect(localStorage.getItem('prime_token')).toBe('valid-token')
    expect(localStorage.getItem('prime_user')).toBe('{"id":1}')
    const nextRequest = successfulAdapter()
    await api.get('/auth/me', { adapter: nextRequest })
    expect(nextRequest.mock.calls[0][0].headers.get('Authorization')).toBe('Bearer valid-token')
  })

  it('clears the identity and default authorization header after a 401 response', async () => {
    setAuthToken('expired-token')
    localStorage.setItem('prime_user', '{"id":1}')
    const error = { response: { status: 401 } }
    const adapter = vi.fn().mockRejectedValue(error)

    await expect(api.get('/test', { adapter })).rejects.toBe(error)

    expect(localStorage.getItem('prime_token')).toBeNull()
    expect(localStorage.getItem('prime_user')).toBeNull()
    expect(api.defaults.headers.common.Authorization).toBeUndefined()

    const nextRequest = successfulAdapter()
    await api.get('/test', { adapter: nextRequest })
    expect(nextRequest.mock.calls[0][0].headers.has('Authorization')).toBe(false)
  })

  it('keeps the persisted identity for other API errors', async () => {
    localStorage.setItem('prime_token', 'test-token')
    localStorage.setItem('prime_user', '{"id":1}')
    const error = { response: { status: 500 } }
    const adapter = vi.fn().mockRejectedValue(error)

    await expect(api.get('/test', { adapter })).rejects.toBe(error)

    expect(localStorage.getItem('prime_token')).toBe('test-token')
    expect(localStorage.getItem('prime_user')).toBe('{"id":1}')
  })
})
