import { useState } from 'react'
import { useLocation, useNavigate, Link } from 'react-router-dom'
import { api, setAuthToken } from '../api/client'
import { Button } from '../components/ui/button'
import { Input, Label } from '../components/ui/input'
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '../components/ui/card'
import { toast } from 'sonner'

export function Login() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const navigate = useNavigate()
  const location = useLocation()
  const authNotice = location.state?.authNotice as { kind: 'success' | 'warning', text: string } | undefined

  const doLogin = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      const res = await api.post('/auth/login-json', { email, password })
      setAuthToken(res.data.access_token)
      localStorage.setItem('prime_user', JSON.stringify(res.data.user))
      toast.success(`Bienvenue ${res.data.user.first_name} !`)
      navigate('/')
    } catch (err: any) {
      setError(typeof err.response?.data?.detail === 'string' ? err.response.data.detail : 'Erreur de connexion')
    } finally { setLoading(false) }
  }

  return (
    <div className="min-h-screen flex">
      <div className="hidden lg:flex flex-1 bg-gradient-to-br from-sky-600 via-blue-600 to-indigo-700 text-white p-12 flex-col justify-between">
        <div>
          <div className="flex items-center gap-3 mb-12">
            <div className="w-10 h-10 rounded-xl bg-white/20 backdrop-blur flex items-center justify-center font-bold">PV</div>
            <span className="font-bold text-xl">Prime Vision Solutions</span>
          </div>
          <h1 className="text-4xl font-bold leading-tight mb-4">Le CRM intelligent<br/>pour TPE & PME</h1>
          <p className="text-blue-100 text-lg max-w-md">Centralisez vos clients, boostez votre pipeline et automatisez votre prospection. Interface 100% en français, hébergeable en Tunisie.</p>
          <div className="grid grid-cols-2 gap-4 mt-10 max-w-md">
            <div className="bg-white/10 backdrop-blur rounded-xl p-4"><div className="text-2xl font-bold">360°</div><div className="text-sm text-blue-100">Fiche client complète</div></div>
            <div className="bg-white/10 backdrop-blur rounded-xl p-4"><div className="text-2xl font-bold">PDF</div><div className="text-sm text-blue-100">Devis professionnels</div></div>
            <div className="bg-white/10 backdrop-blur rounded-xl p-4"><div className="text-2xl font-bold">Kanban</div><div className="text-sm text-blue-100">Pipeline glisser-déposer</div></div>
            <div className="bg-white/10 backdrop-blur rounded-xl p-4"><div className="text-2xl font-bold">IA</div><div className="text-sm text-blue-100">Ollama local gratuit</div></div>
          </div>
        </div>
        <div className="text-sm text-blue-200">© 2026 Prime Vision Solutions — Tunis, Tunisie. Propulsé avec ❤️ pour les entrepreneurs tunisiens et français.</div>
      </div>

      <div className="flex-1 flex items-center justify-center p-6 bg-slate-50 dark:bg-slate-950">
        <Card className="w-full max-w-md shadow-xl">
          <CardHeader className="space-y-1">
            <CardTitle className="text-2xl">Connexion à Prime CRM</CardTitle>
            <CardDescription>Accédez à votre espace commercial privé</CardDescription>
          </CardHeader>
          <CardContent>
            {authNotice && <p role="status" className={`mb-4 rounded-md p-3 text-sm ${authNotice.kind === 'warning' ? 'bg-amber-50 text-amber-900' : 'bg-emerald-50 text-emerald-900'}`}>{authNotice.text}</p>}
            <form onSubmit={doLogin} className="space-y-4">
              <div>
                <Label htmlFor="login-email">Email</Label>
                <Input id="login-email" type="email" autoComplete="username" value={email} onChange={e=>setEmail(e.target.value)} required />
              </div>
              <div>
                <Label htmlFor="login-password">Mot de passe</Label>
                <Input id="login-password" type="password" autoComplete="current-password" value={password} onChange={e=>setPassword(e.target.value)} required />
              </div>
              {error && <p role="alert" className="text-sm text-red-700 dark:text-red-400">{error}</p>}
              <Button type="submit" disabled={loading} className="w-full">{loading ? 'Connexion...' : 'Se connecter'}</Button>
              <p className="text-xs text-center text-muted-foreground">Les comptes sont créés par un administrateur.</p>
            </form>

            <div className="mt-6 text-center text-xs text-muted-foreground">
              <Link to="/" className="hover:underline">Documentation</Link> • <a href="/docs" target="_blank" rel="noreferrer" className="hover:underline">API Docs</a>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
