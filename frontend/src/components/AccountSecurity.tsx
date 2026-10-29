import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, clearAuth } from '../api/client'
import { Button } from './ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from './ui/card'
import { Input, Label } from './ui/input'

export function AccountSecurity() {
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmation, setConfirmation] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const navigate = useNavigate()

  const changePassword = async (event: React.FormEvent) => {
    event.preventDefault()
    setError('')
    if (newPassword !== confirmation) {
      setError('Les nouveaux mots de passe ne correspondent pas.')
      return
    }
    if (Array.from(newPassword).length < 16 || new TextEncoder().encode(newPassword).length > 72 || newPassword !== newPassword.trim()) {
      setError('Choisissez au moins 16 caractères et au plus 72 octets UTF-8, sans espaces aux extrémités.')
      return
    }
    setBusy(true)
    try {
      await api.post('/auth/change-password', { old_password: currentPassword, new_password: newPassword })
      setCurrentPassword('')
      setNewPassword('')
      setConfirmation('')
      clearAuth()
      navigate('/login', {
        replace: true,
        state: { authNotice: { kind: 'success', text: 'Mot de passe modifié. Toutes vos sessions ont été déconnectées. Reconnectez-vous.' } },
      })
    } catch (err: any) {
      const status = err.response?.status
      if (status === 400 && typeof err.response?.data?.detail === 'string') setError(err.response.data.detail)
      else if (status === 429) setError('Trop de tentatives. Réessayez plus tard.')
      else setError('Impossible de confirmer la modification. Si elle a été enregistrée, reconnectez-vous avec le nouveau mot de passe.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card className="max-w-xl">
      <CardHeader>
        <CardTitle>Sécurité du compte</CardTitle>
        <CardDescription>Changez votre propre mot de passe, quel que soit votre rôle.</CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={changePassword} className="space-y-4">
          <p className="text-sm text-muted-foreground">La modification déconnecte toutes vos sessions, sur tous vos appareils, y compris celle-ci.</p>
          <div className="space-y-1">
            <Label htmlFor="current-password">Mot de passe actuel</Label>
            <Input id="current-password" type="password" autoComplete="current-password" value={currentPassword} onChange={event => setCurrentPassword(event.target.value)} required />
          </div>
          <div className="space-y-1">
            <Label htmlFor="new-password">Nouveau mot de passe</Label>
            <Input id="new-password" type="password" autoComplete="new-password" value={newPassword} onChange={event => setNewPassword(event.target.value)} required />
            <p className="text-xs text-muted-foreground">16 caractères minimum, 72 octets UTF-8 maximum, sans espaces aux extrémités.</p>
          </div>
          <div className="space-y-1">
            <Label htmlFor="confirm-password">Confirmer le nouveau mot de passe</Label>
            <Input id="confirm-password" type="password" autoComplete="new-password" value={confirmation} onChange={event => setConfirmation(event.target.value)} required />
          </div>
          {error && <p role="alert" className="text-sm text-red-700 dark:text-red-400">{error}</p>}
          <Button type="submit" disabled={busy}>{busy ? 'Modification...' : 'Modifier le mot de passe'}</Button>
        </form>
      </CardContent>
    </Card>
  )
}
