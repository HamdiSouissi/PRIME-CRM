import { useEffect, useState } from 'react'
import { api } from '../api/client'
import { AccountSecurity } from '../components/AccountSecurity'
import { Card, CardHeader, CardTitle, CardContent } from '../components/ui/card'
import { Button } from '../components/ui/button'
import { Input, Textarea } from '../components/ui/input'
import { toast } from 'sonner'

export function Settings() {
  const [company, setCompany] = useState<any>(null)
  const [companyError, setCompanyError] = useState(false)
  const [users, setUsers] = useState<any[]>([])
  const [stages, setStages] = useState<any[]>([])
  const [form, setForm] = useState<any>({})
  const [newUser, setNewUser] = useState({ email:'', password:'', first_name:'', last_name:'', role:'commercial' })
  const [rules, setRules] = useState<any[]>([])
  const [ruleForm, setRuleForm] = useState({ name:'', trigger_type:'quote_no_response', action_type:'create_task', description:'' })
  const [tab, setTab] = useState('company')

  let signedInUser: { id: number, role: string } | null = null
  try { signedInUser = JSON.parse(localStorage.getItem('prime_user') || 'null') } catch { /* UI only; the API enforces roles */ }
  const isAdmin = signedInUser?.role === 'admin'

  const load = () => {
    setCompanyError(false)
    api.get('/admin/company').then(r=>{ setCompany(r.data); setForm(r.data)}).catch(()=>setCompanyError(true))
    api.get('/users').then(r=>setUsers(r.data)).catch(()=>{})
    api.get('/stages').then(r=>setStages(r.data)).catch(()=>{})
    api.get('/admin/automation/rules').then(r=>setRules(r.data)).catch(()=>{})
  }
  useEffect(()=>{ load() }, [])

  const saveCompany = async (e: React.FormEvent) => {
    e.preventDefault()
    try { await api.put('/admin/company', form); toast.success('Entreprise mise à jour'); load() } catch(e:any){ toast.error(e.response?.data?.detail||'Erreur') }
  }
  const createUser = async (e: React.FormEvent) => {
    e.preventDefault()
    try { await api.post('/users', newUser); toast.success('Utilisateur créé'); setNewUser({email:'', password:'', first_name:'', last_name:'', role:'commercial'}); load() } catch(e:any){ toast.error(e.response?.data?.detail||'Erreur') }
  }
  const createStage = async () => {
    const name = prompt('Nom de l\'étape ?')
    if (!name) return
    await api.post('/stages', { name, color:'#0ea5e9', order: stages.length+1 }); load()
  }
  const createRule = async (e: React.FormEvent) => {
    e.preventDefault()
    try { await api.post('/admin/automation/rules', { ...ruleForm, trigger_config: {}, action_config: { title: `Action auto: ${ruleForm.name}`, priority:'medium', due_in_days:2 }}); toast.success('Règle créée'); setRuleForm({name:'', trigger_type:'quote_no_response', action_type:'create_task', description:''}); load()} catch(e:any){ toast.error('Erreur')}
  }

  const revokeSessions = async (userId: number) => {
    if (!confirm('Déconnecter toutes les sessions de cet utilisateur ?')) return
    try {
      await api.post(`/users/${userId}/revoke-sessions`)
      toast.success('Toutes les sessions de cet utilisateur ont été déconnectées.')
    } catch {
      toast.error('Impossible de confirmer la déconnexion des sessions.')
    }
  }

  return (
    <div className="p-4 lg:p-8 max-w-[1600px] mx-auto space-y-4">
      <h1 className="text-2xl font-bold">Paramètres & Administration</h1>
      <div className="flex gap-2 border-b overflow-x-auto">
        {[
          {id:'company', label:'Entreprise'},
          {id:'security', label:'Sécurité du compte'},
          {id:'users', label:`Utilisateurs (${users.length})`},
          {id:'pipeline', label:'Pipeline'},
          {id:'automation', label:'Automatisations'},
          {id:'exports', label:'Sauvegardes'},
        ].map(t=>(
          <button key={t.id} onClick={()=>setTab(t.id)} className={`px-4 py-2 text-sm font-medium border-b-2 whitespace-nowrap ${tab===t.id ? 'border-sky-500 text-sky-600' : 'border-transparent text-muted-foreground'}`}>{t.label}</button>
        ))}
      </div>

      {tab==='security' && <AccountSecurity />}

      {tab==='company' && !company && (
        <p role={companyError ? 'alert' : 'status'} className="text-sm text-muted-foreground">
          {companyError ? 'Impossible de charger les paramètres de l’entreprise.' : 'Chargement...'}
        </p>
      )}
      {tab==='company' && company && (
        <Card><CardContent className="pt-6">
          <form onSubmit={saveCompany} className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div><label className="text-xs font-medium">Nom entreprise</label><Input value={form.name||''} onChange={e=>setForm({...form, name:e.target.value})} /></div>
            <div><label className="text-xs">Email</label><Input value={form.email||''} onChange={e=>setForm({...form, email:e.target.value})} /></div>
            <div><label className="text-xs">Téléphone</label><Input value={form.phone||''} onChange={e=>setForm({...form, phone:e.target.value})} /></div>
            <div><label className="text-xs">Ville</label><Input value={form.city||''} onChange={e=>setForm({...form, city:e.target.value})} /></div>
            <div className="md:col-span-2"><label className="text-xs">Adresse</label><Input value={form.address||''} onChange={e=>setForm({...form, address:e.target.value})} /></div>
            <div><label className="text-xs">Matricule fiscal</label><Input value={form.tax_id||''} onChange={e=>setForm({...form, tax_id:e.target.value})} /></div>
            <div><label className="text-xs">Devise</label><select value={form.currency||'TND'} onChange={e=>setForm({...form, currency:e.target.value})} className="h-10 w-full rounded-md border px-2 text-sm"><option>TND</option><option>EUR</option><option>USD</option></select></div>
            <div><label className="text-xs">Couleur primaire</label><Input type="color" value={form.primary_color||'#0ea5e9'} onChange={e=>setForm({...form, primary_color:e.target.value})} className="h-10 p-1" /></div>
            <div><label className="text-xs">Préfixe devis</label><Input value={form.quote_prefix||'DEV'} onChange={e=>setForm({...form, quote_prefix:e.target.value})} /></div>
            <div><label className="text-xs">Logo URL</label><Input value={form.logo_url||''} onChange={e=>setForm({...form, logo_url:e.target.value})} placeholder="https://..." /></div>
            <div className="md:col-span-2"><Button type="submit">Enregistrer</Button><span className="text-xs text-muted-foreground ml-3">Logo & couleurs personnalisent les PDF devis</span></div>
          </form>
        </CardContent></Card>
      )}

      {tab==='users' && (
        <div className="space-y-4">
          <Card><CardHeader><CardTitle className="text-sm">Créer un utilisateur</CardTitle></CardHeader><CardContent>
            <form onSubmit={createUser} className="grid grid-cols-1 md:grid-cols-5 gap-2">
              <Input placeholder="Email" value={newUser.email} onChange={e=>setNewUser({...newUser, email:e.target.value})} required />
              <Input placeholder="Prénom" value={newUser.first_name} onChange={e=>setNewUser({...newUser, first_name:e.target.value})} required />
              <Input placeholder="Nom" value={newUser.last_name} onChange={e=>setNewUser({...newUser, last_name:e.target.value})} required />
              <Input type="password" minLength={16} autoComplete="new-password" placeholder="Mot de passe" value={newUser.password} onChange={e=>setNewUser({...newUser, password:e.target.value})} required />
              <div className="flex gap-1"><select value={newUser.role} onChange={e=>setNewUser({...newUser, role:e.target.value})} className="h-10 flex-1 rounded-md border px-2 text-sm"><option value="commercial">Commercial</option><option value="manager">Manager</option><option value="admin">Admin</option><option value="viewer">Lecture seule</option></select><Button type="submit">Créer</Button></div>
            </form>
            <p className="text-xs text-muted-foreground mt-2">Mot de passe : 16 caractères minimum, 72 octets maximum, sans espaces aux extrémités. Rôles vérifiés côté serveur.</p>
          </CardContent></Card>
          <Card><CardContent className="pt-4">
            <div className="overflow-x-auto"><table className="w-full text-sm"><thead><tr className="text-left text-muted-foreground"><th className="p-2">Nom</th><th>Email</th><th>Rôle</th><th>Statut</th><th>Actions</th></tr></thead><tbody>{users.map((u:any)=><tr key={u.id} className="border-t"><td className="p-2">{u.first_name} {u.last_name}</td><td>{u.email}</td><td><span className="text-xs px-1.5 py-0.5 rounded bg-slate-100">{u.role}</span></td><td>{u.is_active ? '✅ Actif' : '⏸️ Inactif'}</td><td>{isAdmin && u.id !== signedInUser?.id && <Button size="sm" variant="outline" onClick={()=>revokeSessions(u.id)}>Déconnecter ses sessions</Button>} <Button size="sm" variant="ghost" onClick={async()=>{ if(!confirm('Supprimer ?')) return; await api.delete(`/users/${u.id}`); load()}}>Supprimer</Button></td></tr>)}</tbody></table></div>
            {isAdmin && <p className="text-xs text-muted-foreground mt-3">La déconnexion d’un utilisateur révoque toutes ses sessions. Pour les vôtres, utilisez « Déconnexion partout » dans le menu.</p>}
          </CardContent></Card>
        </div>
      )}

      {tab==='pipeline' && (
        <Card><CardContent className="pt-4 space-y-3">
          <div className="flex items-center justify-between"><span className="font-medium text-sm">Étapes du pipeline (configurables)</span><Button size="sm" onClick={createStage}>+ Nouvelle étape</Button></div>
          {stages.map((s:any)=><div key={s.id} className="flex items-center justify-between p-3 border rounded-lg"><div className="flex items-center gap-3"><div className="w-4 h-4 rounded-full" style={{background:s.color}}/><span className="font-medium text-sm">{s.name} {s.is_won && '(Gagné)'} {s.is_lost && '(Perdu)'}</span><span className="text-xs text-muted-foreground">{s.opportunities_count} affaires</span></div><Button size="sm" variant="ghost" onClick={async()=>{ await api.delete(`/stages/${s.id}`); load()}}>Supprimer</Button></div>)}
          <p className="text-xs text-muted-foreground">Drag & drop à venir pour réordonner. Les étapes Gagné/Perdu calculent CA signé & taux conversion.</p>
        </CardContent></Card>
      )}

      {tab==='automation' && (
        <div className="space-y-4">
          <Card><CardHeader><CardTitle className="text-sm">Moteur de règles commerciales</CardTitle><p className="text-xs text-muted-foreground">Ex: devis sans réponse 5j → tâche relance | changement étape → notification | inactivité client → alerte</p></CardHeader><CardContent>
            <form onSubmit={createRule} className="grid grid-cols-1 md:grid-cols-4 gap-2">
              <Input placeholder="Nom de la règle" value={ruleForm.name} onChange={e=>setRuleForm({...ruleForm, name:e.target.value})} required />
              <select value={ruleForm.trigger_type} onChange={e=>setRuleForm({...ruleForm, trigger_type:e.target.value})} className="h-10 rounded-md border px-2 text-sm"><option value="quote_no_response">Devis sans réponse</option><option value="opportunity_stage_change">Changement étape</option><option value="client_inactive">Client inactif</option><option value="opportunity_won">Opportunité gagnée</option><option value="before_meeting">Avant rendez-vous</option></select>
              <select value={ruleForm.action_type} onChange={e=>setRuleForm({...ruleForm, action_type:e.target.value})} className="h-10 rounded-md border px-2 text-sm"><option value="create_task">Créer tâche</option><option value="send_notification">Notifier</option><option value="create_alert">Alerte urgente</option></select>
              <Button type="submit">Créer règle</Button>
            </form>
            <div className="mt-4 space-y-2">
              {rules.map((r:any)=><div key={r.id} className="p-3 border rounded-lg flex justify-between items-center"><div><div className="font-medium text-sm">{r.name} <span className={`text-xs px-1.5 py-0.5 rounded ${r.is_active ? 'bg-green-100 text-green-700' : 'bg-slate-100'}`}>{r.is_active ? 'Active' : 'Inactive'}</span></div><div className="text-xs text-muted-foreground">{r.trigger_type} → {r.action_type} • Exécutions: {r.run_count} • {r.last_run_at ? `Dernier: ${new Date(r.last_run_at).toLocaleString('fr-TN')}` : 'Jamais'}</div></div><div className="flex gap-1"><Button size="sm" variant="outline" onClick={async()=>{ await api.put(`/admin/automation/rules/${r.id}`, { is_active: !r.is_active }); load()}}>{r.is_active ? 'Désactiver' : 'Activer'}</Button><Button size="sm" variant="ghost" onClick={async()=>{ await api.delete(`/admin/automation/rules/${r.id}`); load()}}>Suppr.</Button></div></div>)}
              {rules.length===0 && <div className="text-sm text-muted-foreground">Aucune règle — Créez votre première automatisation</div>}
            </div>
            <p className="text-xs text-muted-foreground mt-3">Règles journalisées, protégées contre double exécution, désactivables. Aucun envoi externe sans canal autorisé.</p>
          </CardContent></Card>
        </div>
      )}

      {tab==='exports' && (
        <Card><CardContent className="pt-6 space-y-3">
          <div className="flex gap-2 flex-wrap"><a href={`${api.defaults.baseURL}/admin/backup`}><Button>📦 Télécharger sauvegarde JSON</Button></a><a href={`${api.defaults.baseURL}/import-export/clients/export?format=excel`}><Button variant="outline">Clients Excel</Button></a><a href={`${api.defaults.baseURL}/dashboard/export?format=csv`}><Button variant="outline">Pipeline CSV</Button></a></div>
          <div className="text-xs text-muted-foreground">Sauvegarde: JSON avec clients/opportunités/produits. Restauration: réimport via CSV/Excel + API. Procédure complète dans README.</div>
          <div className="p-3 bg-slate-50 dark:bg-slate-900 rounded text-xs"><div className="font-medium">Journaux d'audit</div><button onClick={async()=>{ const r=await api.get('/admin/audit-logs?limit=10'); alert(JSON.stringify(r.data.items.slice(0,3), null,2))}} className="text-sky-600 hover:underline">Voir derniers logs</button> • Conservation configurable • Accès admin uniquement</div>
        </CardContent></Card>
      )}
    </div>
  )
}
