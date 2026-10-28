import { useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { api, setAuthToken } from '../api/client'
import { Button } from '../components/ui/button'
import { Input, Label } from '../components/ui/input'
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '../components/ui/card'
import { toast } from 'sonner'

export function Login() {
  const [email, setEmail] = useState('admin@primevisionsolutions.tn')
  const [password, setPassword] = useState('Admin123!')
  const [loading, setLoading] = useState(false)
  const [mode, setMode] = useState<'login'|'register'>('login')
  const [firstName, setFirstName] = useState('')
  const [lastName, setLastName] = useState('')
  const [companyName, setCompanyName] = useState('')
  const navigate = useNavigate()

  const doLogin = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true)
    try {
      const res = await api.post('/auth/login-json', { email, password })
      setAuthToken(res.data.access_token)
      localStorage.setItem('prime_user', JSON.stringify(res.data.user))
      toast.success(`Bienvenue ${res.data.user.first_name} !`)
      navigate('/')
    } catch (err: any) {
      toast.error(err.response?.data?.detail || 'Erreur de connexion')
    } finally { setLoading(false) }
  }

  const doRegister = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true)
    try {
      const res = await api.post('/auth/register', { email, password, first_name: firstName, last_name: lastName, company_name: companyName })
      setAuthToken(res.data.access_token)
      localStorage.setItem('prime_user', JSON.stringify(res.data.user))
      toast.success('Compte créé avec succès !')
      navigate('/')
    } catch (err: any) {
      toast.error(err.response?.data?.detail || 'Erreur inscription')
    } finally { setLoading(false) }
  }

  const seedAdmin = async () => {
    try {
      const res = await api.post('/auth/seed-admin')
      toast.success(`Admin créé: ${res.data.email}`)
      setEmail(res.data.email)
    } catch (err: any) {
      toast.error(err.response?.data?.detail || 'Admin existe déjà')
    }
  }

  return (
    <div className="min-h-screen flex">
      {/* Left branding */}
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

      {/* Right form */}
      <div className="flex-1 flex items-center justify-center p-6 bg-slate-50 dark:bg-slate-950">
        <Card className="w-full max-w-md shadow-xl">
          <CardHeader className="space-y-1">
            <CardTitle className="text-2xl">{mode === 'login' ? 'Connexion à Prime CRM' : 'Créer votre espace'}</CardTitle>
            <CardDescription>{mode === 'login' ? 'Accédez à votre espace commercial' : 'Démarrage en 30 secondes, sans carte bancaire'}</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="flex gap-2 mb-6">
              <button onClick={() => setMode('login')} className={`flex-1 py-2 rounded-lg text-sm font-medium ${mode==='login' ? 'bg-sky-500 text-white' : 'bg-slate-100 dark:bg-slate-800'}`}>Connexion</button>
              <button onClick={() => setMode('register')} className={`flex-1 py-2 rounded-lg text-sm font-medium ${mode==='register' ? 'bg-sky-500 text-white' : 'bg-slate-100 dark:bg-slate-800'}`}>Inscription</button>
            </div>

            {mode === 'login' ? (
              <form onSubmit={doLogin} className="space-y-4">
                <div><Label>Email</Label><Input type="email" value={email} onChange={e=>setEmail(e.target.value)} required placeholder="admin@primevisionsolutions.tn" /></div>
                <div><Label>Mot de passe</Label><Input type="password" value={password} onChange={e=>setPassword(e.target.value)} required /></div>
                <Button type="submit" disabled={loading} className="w-full">{loading ? 'Connexion...' : 'Se connecter'}</Button>
                <div className="text-xs text-center text-muted-foreground">Compte démo: admin@primevisionsolutions.tn / Admin123!</div>
                <Button type="button" variant="outline" className="w-full text-xs" onClick={seedAdmin}>Initialiser le compte admin (1er lancement)</Button>
              </form>
            ) : (
              <form onSubmit={doRegister} className="space-y-4">
                <div className="grid grid-cols-2 gap-3"><div><Label>Prénom</Label><Input value={firstName} onChange={e=>setFirstName(e.target.value)} required /></div><div><Label>Nom</Label><Input value={lastName} onChange={e=>setLastName(e.target.value)} required /></div></div>
                <div><Label>Nom de l'entreprise</Label><Input value={companyName} onChange={e=>setCompanyName(e.target.value)} placeholder="Ma Société" /></div>
                <div><Label>Email</Label><Input type="email" value={email} onChange={e=>setEmail(e.target.value)} required /></div>
                <div><Label>Mot de passe</Label><Input type="password" value={password} onChange={e=>setPassword(e.target.value)} required /></div>
                <Button type="submit" disabled={loading} className="w-full">{loading ? 'Création...' : 'Créer mon espace Prime CRM'}</Button>
                <p className="text-xs text-muted-foreground text-center">En vous inscrivant, vous acceptez la confidentialité stricte de vos données (séparation par entreprise).</p>
              </form>
            )}

            <div className="mt-6 text-center text-xs text-muted-foreground">
              <Link to="/" className="hover:underline">Documentation</Link> • <a href="/docs" target="_blank" className="hover:underline">API Docs</a>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
