import { useEffect, useState } from 'react'
import { api } from '../api/client'
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card'
import { Button } from '../components/ui/button'
import { Input, Badge } from '../components/ui/input'
import { Calendar, Clock, AlertTriangle, CheckCircle2, Plus } from 'lucide-react'
import { formatDate } from '../lib/utils'
import { toast } from 'sonner'

export function Activities() {
  const [activities, setActivities] = useState<any[]>([])
  const [overdue, setOverdue] = useState<any[]>([])
  const [view, setView] = useState<'list'|'day'|'week'|'month'>('list')
  const [dateFilter, setDateFilter] = useState(new Date().toISOString().slice(0,10))
  const [showCreate, setShowCreate] = useState(false)
  const [clients, setClients] = useState<any[]>([])
  const [form, setForm] = useState({ title:'', type:'task', priority:'medium', due_date:'', due_time:'', client_id:'', description:'', duration_minutes:'', location:'' })

  const load = () => {
    if (view==='list') api.get('/activities').then(r=>setActivities(r.data))
    else api.get(`/activities?view=${view}&date_filter=${dateFilter}`).then(r=>setActivities(r.data))
    api.get('/activities/overdue').then(r=>setOverdue(r.data))
  }
  useEffect(()=>{ load(); api.get('/clients?page=1&page_size=100').then(r=>setClients(r.data.items)) }, [view, dateFilter])

  const create = async (e: React.FormEvent) => {
    e.preventDefault()
    try {
      await api.post('/activities', { ...form, client_id: form.client_id ? Number(form.client_id) : null, duration_minutes: form.duration_minutes ? Number(form.duration_minutes) : null })
      toast.success('Activité créée'); setShowCreate(false); setForm({ title:'', type:'task', priority:'medium', due_date:'', due_time:'', client_id:'', description:'', duration_minutes:'', location:'' }); load()
    } catch(e:any){ toast.error(e.response?.data?.detail||'Erreur')}
  }
  const toggle = async (id:number) => { await api.post(`/activities/${id}/complete`); load() }

  return (
    <div className="p-4 lg:p-8 max-w-[1600px] mx-auto space-y-4">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div><h1 className="text-2xl font-bold">Agenda commercial</h1><p className="text-sm text-muted-foreground">Rendez-vous, tâches et relances • Vues jour / semaine / mois • Rappels configurables</p></div>
        <Button onClick={()=>setShowCreate(true)}><Plus className="w-4 h-4 mr-1"/>Nouvelle activité</Button>
      </div>

      {overdue.length>0 && (
        <Card className="border-red-200 bg-red-50 dark:bg-red-950/20"><CardContent className="pt-3 flex gap-2"><AlertTriangle className="w-4 h-4 text-red-600 mt-0.5"/><div className="text-sm"><div className="font-medium text-red-800 dark:text-red-200">{overdue.length} tâche(s) en retard</div><div className="flex flex-wrap gap-2 mt-1">{overdue.slice(0,5).map((a:any)=><span key={a.id} className="text-xs bg-white px-2 py-1 rounded border">{a.title} — {formatDate(a.due_date)}</span>)}</div></div></CardContent></Card>
      )}

      <Card><CardContent className="pt-4 flex flex-wrap gap-2 items-center">
        <div className="flex gap-1">
          <Button size="sm" variant={view==='list' ? 'default' : 'outline'} onClick={()=>setView('list')}>Liste</Button>
          <Button size="sm" variant={view==='day' ? 'default' : 'outline'} onClick={()=>setView('day')}>Jour</Button>
          <Button size="sm" variant={view==='week' ? 'default' : 'outline'} onClick={()=>setView('week')}>Semaine</Button>
          <Button size="sm" variant={view==='month' ? 'default' : 'outline'} onClick={()=>setView('month')}>Mois</Button>
        </div>
        {view!=='list' && <Input type="date" value={dateFilter} onChange={e=>setDateFilter(e.target.value)} className="w-40" />}
        <span className="text-xs text-muted-foreground ml-auto">Intégration future Google Calendar / Outlook (API prête)</span>
      </CardContent></Card>

      {showCreate && (
        <Card><CardContent className="pt-6">
          <form onSubmit={create} className="grid grid-cols-1 md:grid-cols-3 gap-3">
            <div><label className="text-xs">Titre *</label><Input value={form.title} onChange={e=>setForm({...form, title:e.target.value})} required /></div>
            <div><label className="text-xs">Type</label><select value={form.type} onChange={e=>setForm({...form, type:e.target.value})} className="h-10 w-full rounded-md border px-2 text-sm"><option value="task">Tâche</option><option value="call">Appel</option><option value="meeting">Rendez-vous</option><option value="email">Email</option></select></div>
            <div><label className="text-xs">Priorité</label><select value={form.priority} onChange={e=>setForm({...form, priority:e.target.value})} className="h-10 w-full rounded-md border px-2 text-sm"><option value="low">Basse</option><option value="medium">Moyenne</option><option value="high">Haute</option><option value="urgent">Urgente</option></select></div>
            <div><label className="text-xs">Échéance</label><Input type="date" value={form.due_date} onChange={e=>setForm({...form, due_date:e.target.value})} /></div>
            <div><label className="text-xs">Heure</label><Input type="time" value={form.due_time} onChange={e=>setForm({...form, due_time:e.target.value})} /></div>
            <div><label className="text-xs">Durée (min)</label><Input type="number" value={form.duration_minutes} onChange={e=>setForm({...form, duration_minutes:e.target.value})} /></div>
            <div><label className="text-xs">Client</label><select value={form.client_id} onChange={e=>setForm({...form, client_id:e.target.value})} className="h-10 w-full rounded-md border px-2 text-sm"><option value="">Aucun</option>{clients.map((c:any)=><option key={c.id} value={c.id}>{c.company_name}</option>)}</select></div>
            <div><label className="text-xs">Lieu</label><Input value={form.location} onChange={e=>setForm({...form, location:e.target.value})} /></div>
            <div className="md:col-span-3"><label className="text-xs">Description</label><Input value={form.description} onChange={e=>setForm({...form, description:e.target.value})} /></div>
            <div className="flex gap-2"><Button type="submit">Créer</Button><Button type="button" variant="outline" onClick={()=>setShowCreate(false)}>Annuler</Button></div>
          </form>
        </CardContent></Card>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="lg:col-span-2 space-y-2">
          {activities.map((a:any)=>(
            <Card key={a.id} className={`${a.priority==='urgent' ? 'border-red-300' : a.priority==='high' ? 'border-amber-300' : ''} ${a.is_completed ? 'opacity-60' : ''}`}>
              <CardContent className="pt-4 flex items-start gap-3">
                <button onClick={()=>toggle(a.id)} className={`mt-1 w-5 h-5 rounded-full border-2 flex items-center justify-center ${a.is_completed ? 'bg-green-500 border-green-500 text-white' : 'border-slate-300'}`}>{a.is_completed && <CheckCircle2 className="w-3 h-3"/>}</button>
                <div className="flex-1">
                  <div className="font-medium text-sm flex items-center gap-2">{a.title} <Badge variant={a.type==='meeting' ? 'default' : 'secondary'}>{a.type}</Badge> <span className={`text-xs px-1.5 py-0.5 rounded ${a.priority==='urgent' ? 'bg-red-100 text-red-700' : a.priority==='high' ? 'bg-amber-100 text-amber-700' : 'bg-slate-100'}`}>{a.priority}</span> {a.is_completed && <span className="text-xs text-green-600">Terminé</span>}</div>
                  <div className="text-xs text-muted-foreground mt-1 flex flex-wrap gap-2"><span className="flex items-center gap-1"><Calendar className="w-3 h-3"/>{formatDate(a.due_date)} {a.due_time || ''}</span>{a.duration_minutes && <span className="flex items-center gap-1"><Clock className="w-3 h-3"/>{a.duration_minutes} min</span>}{a.client_name && <span>{a.client_name}</span>}{a.owner_name && <span>• {a.owner_name}</span>}</div>
                  {a.description && <div className="text-xs mt-1">{a.description}</div>}
                  {a.location && <div className="text-xs text-muted-foreground">📍 {a.location}</div>}
                </div>
                <Button size="sm" variant="ghost" onClick={async()=>{ if(!confirm('Supprimer ?')) return; await api.delete(`/activities/${a.id}`); load() }}>✕</Button>
              </CardContent>
            </Card>
          ))}
          {activities.length===0 && <div className="text-center py-12 text-muted-foreground">Aucune activité pour cette période</div>}
        </div>
        <div className="space-y-4">
          <Card><CardHeader><CardTitle className="text-sm">Rappels</CardTitle></CardHeader><CardContent className="text-xs text-muted-foreground">Les rappels configurables enverront une notification dans l'application avant l'échéance. Connectez Google Calendar / Outlook depuis Paramètres pour synchroniser.</CardContent></Card>
          <Card><CardHeader><CardTitle className="text-sm">Notifications</CardTitle></CardHeader><CardContent className="space-y-2 text-xs">{activities.filter((a:any)=>!a.is_completed).slice(0,5).map((a:any)=><div key={a.id} className="p-2 rounded bg-slate-50 dark:bg-slate-800"><div className="font-medium">{a.title}</div><div className="text-muted-foreground">Échéance {formatDate(a.due_date)}</div></div>)}</CardContent></Card>
        </div>
      </div>
    </div>
  )
}
