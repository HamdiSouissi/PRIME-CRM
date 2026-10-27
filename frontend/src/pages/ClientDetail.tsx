import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { api } from '../api/client'
import { Card, CardHeader, CardTitle, CardContent } from '../components/ui/card'
import { Button } from '../components/ui/button'
import { Input, Textarea } from '../components/ui/input'
import { Building2, Mail, Phone, MapPin, Plus, Bot, FileText, Calendar, Trash2 } from 'lucide-react'
import { formatDate, formatCurrency } from '../lib/utils'
import { toast } from 'sonner'

export function ClientDetail() {
  const { id } = useParams()
  const [data, setData] = useState<any>(null)
  const [tab, setTab] = useState('overview')
  const [aiSummary, setAiSummary] = useState('')
  const [aiLoading, setAiLoading] = useState(false)
  const [note, setNote] = useState('')
  const [contactForm, setContactForm] = useState({ first_name:'', last_name:'', email:'', phone:'', position:'' })
  const [activityForm, setActivityForm] = useState({ title:'', type:'task', due_date:'', priority:'medium' })

  const load = () => api.get(`/clients/${id}/full`).then(r=>setData(r.data))
  useEffect(()=>{ load() }, [id])

  const addContact = async (e: React.FormEvent) => {
    e.preventDefault()
    try { await api.post(`/clients/${id}/contacts`, contactForm); toast.success('Contact ajouté'); setContactForm({first_name:'', last_name:'', email:'', phone:'', position:''}); load() } catch(e:any){ toast.error('Erreur') }
  }
  const addActivity = async (e: React.FormEvent) => {
    e.preventDefault()
    try { await api.post('/activities', { ...activityForm, client_id: Number(id) }); toast.success('Activité créée'); setActivityForm({title:'', type:'task', due_date:'', priority:'medium'}); load() } catch(e:any){ toast.error('Erreur') }
  }
  const addNoteActivity = async () => {
    if (!note.trim()) return
    try { await api.post('/activities', { title: note.slice(0,60), description: note, type: 'note', client_id: Number(id), status: 'done', is_completed: true }); setNote(''); toast.success('Note ajoutée'); load() } catch {}
  }
  const summarize = async () => {
    setAiLoading(true)
    try {
      const res = await api.post('/ai/summary/client', { client_id: Number(id) })
      setAiSummary(res.data.content)
    } catch(e:any){ toast.error(e.response?.data?.detail || 'IA non configurée'); setAiSummary('Configurez Ollama ou CodeCraftAPI dans Paramètres > IA. Le CRM reste fonctionnel sans IA.') } finally { setAiLoading(false) }
  }

  if (!data) return <div className="p-8">Chargement...</div>
  const c = data.client

  return (
    <div className="p-4 lg:p-8 max-w-[1600px] mx-auto space-y-4">
      <div className="flex items-center gap-2 text-sm text-muted-foreground"><a href="/clients" className="hover:underline">Clients</a> / <span className="text-foreground font-medium">{c.company_name}</span></div>

      <Card className="overflow-hidden">
        <div className="h-24 bg-gradient-to-r from-sky-500 to-blue-600"></div>
        <CardContent className="pt-4">
          <div className="flex flex-col md:flex-row md:items-start gap-4">
            <div className="w-16 h-16 rounded-xl bg-white dark:bg-slate-900 border shadow flex items-center justify-center -mt-8"><Building2 className="w-8 h-8 text-sky-600"/></div>
            <div className="flex-1">
              <h1 className="text-xl font-bold">{c.company_name}</h1>
              <div className="text-sm text-muted-foreground flex flex-wrap gap-3 mt-1">
                <span className="flex items-center gap-1"><Mail className="w-3 h-3"/>{c.email || '—'}</span>
                <span className="flex items-center gap-1"><Phone className="w-3 h-3"/>{c.phone || '—'}</span>
                <span className="flex items-center gap-1"><MapPin className="w-3 h-3"/>{c.city || ''} {c.country}</span>
              </div>
              <div className="flex gap-2 mt-2">
                <span className="text-xs px-2 py-1 rounded-full bg-sky-50 text-sky-700">{c.type}</span>
                {c.sector && <span className="text-xs px-2 py-1 rounded-full bg-slate-100">{c.sector}</span>}
                {c.source && <span className="text-xs px-2 py-1 rounded-full bg-violet-50 text-violet-700">{c.source}</span>}
              </div>
            </div>
            <div className="flex gap-2">
              <Button onClick={summarize} disabled={aiLoading} className="bg-gradient-to-r from-violet-500 to-purple-600"><Bot className="w-4 h-4 mr-1"/>{aiLoading ? 'Résumé...' : 'Résumé IA'}</Button>
            </div>
          </div>
          {aiSummary && <div className="mt-4 p-4 rounded-xl bg-violet-50 dark:bg-violet-950/30 border border-violet-200 text-sm whitespace-pre-wrap">{aiSummary}<div className="text-xs text-muted-foreground mt-2">⚠️ Généré par IA — Vérifiez les données sensibles</div></div>}
        </CardContent>
      </Card>

      <div className="flex gap-2 flex-wrap border-b">
        {[
          {id:'overview', label:'Vue 360°'},
          {id:'contacts', label:`Contacts (${data.contacts.length})`},
          {id:'opportunities', label:`Opportunités (${data.opportunities.length})`},
          {id:'activities', label:`Activités (${data.activities.length})`},
          {id:'quotes', label:`Devis (${data.quotes.length})`},
          {id:'notes', label:'Notes & Fichiers'},
        ].map(t=>(
          <button key={t.id} onClick={()=>setTab(t.id)} className={`px-4 py-2 text-sm font-medium border-b-2 ${tab===t.id ? 'border-sky-500 text-sky-600' : 'border-transparent text-muted-foreground hover:text-foreground'}`}>{t.label}</button>
        ))}
      </div>

      {tab==='overview' && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          <Card className="lg:col-span-2">
            <CardHeader><CardTitle className="text-sm">Informations</CardTitle></CardHeader>
            <CardContent className="grid grid-cols-2 gap-4 text-sm">
              <div><div className="text-muted-foreground text-xs">Raison sociale</div><div className="font-medium">{c.legal_name || c.company_name}</div></div>
              <div><div className="text-muted-foreground text-xs">Matricule fiscal</div><div>{c.tax_id || '—'}</div></div>
              <div><div className="text-muted-foreground text-xs">Adresse</div><div>{c.address || '—'}</div></div>
              <div><div className="text-muted-foreground text-xs">Ville / Pays</div><div>{c.city || '—'} {c.country}</div></div>
              <div><div className="text-muted-foreground text-xs">Site web</div><div>{c.website || '—'}</div></div>
              <div><div className="text-muted-foreground text-xs">Propriétaire</div><div>{c.owner_name || '—'}</div></div>
              <div className="col-span-2"><div className="text-muted-foreground text-xs">Notes</div><div className="whitespace-pre-wrap">{c.notes || 'Aucune note'}</div></div>
            </CardContent>
          </Card>
          <div className="space-y-4">
            <Card><CardHeader><CardTitle className="text-sm">Chiffres clés</CardTitle></CardHeader><CardContent className="space-y-2 text-sm">
              <div className="flex justify-between"><span>Opportunités</span><b>{data.opportunities.length}</b></div>
              <div className="flex justify-between"><span>Devis</span><b>{data.quotes.length}</b></div>
              <div className="flex justify-between"><span>Activités</span><b>{data.activities.length}</b></div>
              <div className="flex justify-between"><span>Total devis</span><b>{formatCurrency(data.quotes.reduce((s:any,q:any)=>s+(q.total||0),0))}</b></div>
            </CardContent></Card>
            <Card><CardHeader><CardTitle className="text-sm">Historique chronologique</CardTitle></CardHeader><CardContent className="space-y-2 max-h-64 overflow-auto scrollbar-thin">
              {data.history.map((h:any)=><div key={h.id} className="text-xs border-l-2 border-sky-200 pl-3 py-1"><div className="font-medium">{h.title}</div><div className="text-muted-foreground">{h.type} • {formatDate(h.created_at)}</div></div>)}
              {data.history.length===0 && <div className="text-xs text-muted-foreground">Aucun historique</div>}
            </CardContent></Card>
          </div>
        </div>
      )}

      {tab==='contacts' && (
        <Card><CardContent className="pt-6 space-y-4">
          <form onSubmit={addContact} className="grid grid-cols-1 md:grid-cols-5 gap-2">
            <Input placeholder="Prénom *" value={contactForm.first_name} onChange={e=>setContactForm({...contactForm, first_name:e.target.value})} required />
            <Input placeholder="Nom *" value={contactForm.last_name} onChange={e=>setContactForm({...contactForm, last_name:e.target.value})} required />
            <Input placeholder="Email" value={contactForm.email} onChange={e=>setContactForm({...contactForm, email:e.target.value})} />
            <Input placeholder="Téléphone" value={contactForm.phone} onChange={e=>setContactForm({...contactForm, phone:e.target.value})} />
            <Button type="submit"><Plus className="w-4 h-4 mr-1"/>Ajouter</Button>
          </form>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {data.contacts.map((ct:any)=><div key={ct.id} className="p-3 border rounded-lg flex justify-between items-center"><div><div className="font-medium text-sm">{ct.first_name} {ct.last_name} {ct.is_primary && '⭐'}</div><div className="text-xs text-muted-foreground">{ct.email || ''} {ct.phone || ''} {ct.position && `• ${ct.position}`}</div></div><Button size="sm" variant="ghost" onClick={async()=>{ await api.delete(`/clients/${id}/contacts/${ct.id}`); load() }}><Trash2 className="w-3 h-3"/></Button></div>)}
            {data.contacts.length===0 && <div className="text-sm text-muted-foreground">Aucun contact — Ajoutez le premier contact de cette entreprise</div>}
          </div>
        </CardContent></Card>
      )}

      {tab==='opportunities' && (
        <Card><CardContent className="pt-4">
          <div className="space-y-2">
            {data.opportunities.map((o:any)=><div key={o.id} className="p-3 border rounded-lg flex justify-between items-center"><div><div className="font-medium text-sm">{o.title}</div><div className="text-xs text-muted-foreground">{formatCurrency(o.amount)} • {o.probability}% • {formatDate(o.created_at)}</div></div><a href="/pipeline" className="text-xs text-sky-600 hover:underline flex items-center gap-1"><Calendar className="w-3 h-3"/>Pipeline</a></div>)}
            {data.opportunities.length===0 && <div className="text-sm text-muted-foreground">Aucune opportunité — Créez une opportunité depuis le pipeline</div>}
          </div>
        </CardContent></Card>
      )}

      {tab==='activities' && (
        <Card><CardContent className="pt-6 space-y-4">
          <form onSubmit={addActivity} className="grid grid-cols-1 md:grid-cols-5 gap-2">
            <Input placeholder="Titre *" value={activityForm.title} onChange={e=>setActivityForm({...activityForm, title:e.target.value})} required />
            <select value={activityForm.type} onChange={e=>setActivityForm({...activityForm, type:e.target.value})} className="h-10 rounded-md border px-2 text-sm"><option value="task">Tâche</option><option value="call">Appel</option><option value="meeting">Rendez-vous</option><option value="email">Email</option></select>
            <Input type="date" value={activityForm.due_date} onChange={e=>setActivityForm({...activityForm, due_date:e.target.value})} />
            <select value={activityForm.priority} onChange={e=>setActivityForm({...activityForm, priority:e.target.value})} className="h-10 rounded-md border px-2 text-sm"><option value="low">Basse</option><option value="medium">Moyenne</option><option value="high">Haute</option><option value="urgent">Urgente</option></select>
            <Button type="submit"><Plus className="w-4 h-4 mr-1"/>Créer</Button>
          </form>
          <div className="space-y-2">
            {data.activities.map((a:any)=><div key={a.id} className="p-3 border rounded-lg"><div className="font-medium text-sm">{a.title} <span className="text-xs px-1.5 py-0.5 rounded bg-slate-100">{a.type}</span> {a.is_completed && '✅'}</div><div className="text-xs text-muted-foreground">{a.description || ''} • Échéance: {a.due_date || '—'} • {a.owner_name || ''}</div></div>)}
            {data.activities.length===0 && <div className="text-sm text-muted-foreground">Aucune activité</div>}
          </div>
        </CardContent></Card>
      )}

      {tab==='quotes' && (
        <Card><CardContent className="pt-4 space-y-2">
          {data.quotes.map((q:any)=><div key={q.id} className="p-3 border rounded-lg flex justify-between items-center"><div><div className="font-medium text-sm">{q.number} — {q.title}</div><div className="text-xs text-muted-foreground">{q.status} • {formatCurrency(q.total)} • {formatDate(q.created_at)}</div></div><a href={`/devis`} className="text-xs text-sky-600 hover:underline flex items-center gap-1"><FileText className="w-3 h-3"/>Voir devis</a></div>)}
          {data.quotes.length===0 && <div className="text-sm text-muted-foreground">Aucun devis</div>}
        </CardContent></Card>
      )}

      {tab==='notes' && (
        <Card><CardContent className="pt-6 space-y-4">
          <div className="space-y-2">
            <Textarea placeholder="Ajouter une note, un commentaire ou un compte rendu..." value={note} onChange={e=>setNote(e.target.value)} rows={4} />
            <div className="flex gap-2">
              <Button onClick={addNoteActivity}>Ajouter la note</Button>
              <Button variant="outline" onClick={async()=>{ if(!note.trim()) return; try { const r=await api.post('/ai/generate', { prompt: `Prépare un compte rendu structuré à partir de ces notes: ${note}`, feature:'meeting_notes'}); setNote(r.data.content)} catch{}}}>Améliorer avec IA (facultatif)</Button>
            </div>
            <p className="text-xs text-muted-foreground">Les fichiers peuvent être joints via l'activité (10 Mo max). L'IA n'est jamais obligatoire pour utiliser les notes.</p>
          </div>
          <div className="space-y-2">
            {data.activities.filter((a:any)=>a.type==='note').map((a:any)=><div key={a.id} className="p-3 bg-amber-50 dark:bg-amber-950/20 border rounded-lg text-sm whitespace-pre-wrap">{a.description || a.title}<div className="text-xs text-muted-foreground mt-1">{formatDate(a.created_at)}</div></div>)}
          </div>
        </CardContent></Card>
      )}
    </div>
  )
}
