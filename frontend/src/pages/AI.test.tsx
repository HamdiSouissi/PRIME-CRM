// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import type { AxiosResponse } from 'axios'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { toast } from 'sonner'
import { api } from '../api/client'
import { AIPage } from './AI'

vi.mock('../api/client', () => ({
  api: { get: vi.fn(), post: vi.fn(), delete: vi.fn() },
}))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

const staleProvider = {
  id: 12,
  name: 'Ancien fournisseur',
  provider: 'openai_compat',
  api_base_url: 'https://provider.example.invalid/v1',
  api_key_masked: '***',
  api_key_needs_reset: true,
  model_id: 'dummy-model',
  is_active: true,
  is_default: true,
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(api.get).mockImplementation(async (url) => ({
    data: url === '/ai/providers' ? [staleProvider] : { active_providers: 1, message: 'IA facultative' },
  }) as AxiosResponse)
  vi.mocked(api.post).mockResolvedValue({ data: {} } as AxiosResponse)
})

afterEach(() => cleanup())

describe('AI provider credentials', () => {
  it('warns when a legacy or unreadable credential requires replacement', async () => {
    render(<AIPage />)
    const warning = await screen.findByRole('alert')
    expect(warning.textContent).toContain('Clé ancienne ou illisible')
    expect(warning.textContent).toContain('supprimer et recréer')
    expect(screen.queryByText(/sk-fake/i)).toBeNull()
  })

  it('clears the typed credential after saving and when cancelling', async () => {
    render(<AIPage />)
    fireEvent.click(screen.getByRole('button', { name: '+ CodeCraftAPI' }))
    fireEvent.change(screen.getByPlaceholderText('sk-...'), { target: { value: 'sk-fake-only-for-ui-test' } })
    fireEvent.click(screen.getByRole('button', { name: 'Enregistrer' }))
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith('Fournisseur CodeCraftAPI créé'))
    fireEvent.click(screen.getByRole('button', { name: '+ CodeCraftAPI' }))
    expect((screen.getByPlaceholderText('sk-...') as HTMLInputElement).value).toBe('')
    fireEvent.change(screen.getByPlaceholderText('sk-...'), { target: { value: 'sk-fake-only-for-cancel' } })
    fireEvent.click(screen.getByRole('button', { name: 'Annuler' }))
    fireEvent.click(screen.getByRole('button', { name: '+ CodeCraftAPI' }))
    expect((screen.getByPlaceholderText('sk-...') as HTMLInputElement).value).toBe('')
  })
})
