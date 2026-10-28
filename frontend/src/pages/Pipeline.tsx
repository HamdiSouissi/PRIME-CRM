import { useEffect, useState } from 'react'
import { api } from '../api/client'
import { Card, CardHeader, CardTitle, CardContent } from '../components/ui/card'
import { Button } from '../components/ui/button'
import { Input, Select } from '../components/ui/input'
import { DndContext, DragEndEvent, closestCenter, PointerSensor, useSensor, useSensors } from '@dnd-kit/core'
import { useDroppable, useDraggable } from '@dnd-kit/core'
import { formatCurrency, formatDate } from '../lib/utils'
import { Plus, Search, Filter, AlertTriangle } from 'lucide-react'
import { toast } from 'sonner'

function DraggableCard({ opp, onClick }: any) {
  const { attributes, listeners, setNodeRef, transform } = useDraggable({ id: String(opp.id) })
  const style = transform ? { transform: `translate3d(${transform.x}px, ${transform.y}px, 0)` } : undefined
  return (
    <div ref={setNodeRef} style={style} {...attributes} {...listeners} onClick={onClick} className="bg-white dark:bg-slate-800 border rounded-lg p-3 shadow-sm hover:shadow-md cursor-grab active:cursor-grabbing space-y-1">
      <div className="font-medium text-sm truncate">{opp.title}</div>
      <div className="text-xs text-muted-foreground truncate">{opp.client_name}</div>
      <div className="flex items-center justify-between mt-1">
        <span className="text-xs font-bold">{formatCurrency(opp.amount)}</span>
        <span className="text-xs px-1.5 py-0.5 rounded bg-slate-100 dark:bg-slate-700">{opp.probability}%</span>
      </div>
      <div className="text-xs text-muted-foreground">{formatDate(opp.expected_close_date)}</div>
      {opp.next_action && <div className="text-xs bg-amber-50 text-amber-800 px-1.5 py-0.5 rounded truncate">→ {opp.next_action}</div>}
      <div className="text-xs text-muted-foreground">{opp.owner_name || ''}</div>
    </div>
  )
}
function DroppableColumn({ stage, children, count, value }: any) {
  const { setNodeRef, isOver } = useDroppable({ id: String(stage.id) })
  return (
    <div ref={setNodeRef} className={`flex-1 min-w-[280px] rounded-xl border-2 ${isOver ? 'border-sky-400 bg-sky-50 dark:bg-sky-950/20' : 'border-slate-200 dark:border-slate-700 bg-slate-50/50 dark:bg-slate-900/20'} flex flex-col`}>
      <div className="p-3 border-b dark:border-slate-700" style={{ borderTopWidth: '4px', borderTopColor: stage.color }}>
        <div className="font-semibold text-sm">{stage.name}</div>
        <div className="text-xs text-muted-foreground">{count} affaires • {formatCurrency(value)}</div>
        {stage.is_won && <span className="text-xs bg-green-100 text-green-700 px-1.5 py-0.5 rounded">Gagné</span>}
        {stage.is_lost && <span className="text-xs bg-red-100 text-red-700 px-1.5 py-0.5 rounded">Perdu</span>}
      </div>
      <div className="flex-1 p-2 space-y-2 overflow-auto scrollbar-thin min-h-[200px]">{children}</div>
    </div>
  )
}

export function Pipeline() {
  const [pipeline, setPipeline] = useState<any>(null)
  const [alerts, setAlerts] = useState<any[]>([])
  const [search, setSearch] = useState('')
  const [showCreate, setShowCreate] = useState(false)
  const [clients, setClients] = useState<any[]>([])
  const [users, setUsers] = useState<any[]>([])
  const [form, setForm] = useState({ title:'', client_id:'', stage_id:'', amount:'', probability:'50', expected_close_date:'', source:'', next_action:'' })
  const [movingOpp, setMovingOpp] = useState<any>(null)
  const [lossReason, setLossReason] = useState('')
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 8 } }))

  const load = () => {
    api.get('/opportunities/pipeline').then(r=>setPipeline(r.data))
    api.get('/opportunities/alerts').then(r=>setAlerts(r.data))
  }
  useEffect(()=>{ load(); api.get('/clients?page=1&page_size=100').then(r=>setClients(r.data.items)); api.get('/users').then(r=>setUsers(r.data)) }, [])

  const onDragEnd = async (event: DragEndEvent) => {
    const { active, over } = event
    if (!over) return
    const oppId = Number(active.id)
    const newStageId = Number(over.id)
    const opp = pipeline.opportunities.find((o:any)=>o.id===oppId)
    if (!opp || opp.stage_id===newStageId) return
    const stage = pipeline.stages.find((s:any)=>s.id===newStageId)
    if (stage?.is_lost) {
      setMovingOpp({ id: oppId, stageId: newStageId, title: opp.title })
      return
    }
    try { await api.post(`/opportunities/${oppId}/move`, { stage_id: newStageId }); toast.success('Opportunité déplacée'); load() } catch(e:any){ toast.error(e.response?.data?.detail || 'Erreur') }
  }

  const confirmMove = async () => {
    if (!lossReason.trim()) { toast.error('Raison de perte obligatoire'); return }
    try { await api.post(`/opportunities/${movingOpp.id}/move`, { stage_id: movingOpp.stageId, loss_reason: lossReason }); toast.success('Déplacé en Perdu'); setMovingOpp(null); setLossReason(''); load() } catch(e:any){ toast.error(e.response?.data?.detail||'Erreur')}
  }

  const createOpp = async (e: React.FormEvent) => {
    e.preventDefault()
    try {
      await api.post('/opportunities', { ...form, client_id: Number(form.client_id), stage_id: Number(form.stage_id), amount: Number(form.amount), probability: Number(form.probability) })
      toast.success('Opportunité créée'); setShowCreate(false); load()
    } catch(e:any){ toast.error(e.response?.data?.detail||'Erreur') }
  }

  if (!pipeline) return <div className="p-8">Chargement du pipeline...</div>

  const filtered = search ? pipeline.opportunities.filter((o:any)=> o.title.toLowerCase().includes(search.toLowerCase()) || o.client_name?.toLowerCase().includes(search.toLowerCase())) : pipeline.opportunities

  return (
    <div className="p-4 lg:p-8 max-w-[1600px] mx-auto space-y-4">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div><h1 className="text-2xl font-bold">Pipeline commercial</h1><p className="text-sm text-muted-foreground">Glissez-déposez vos affaires • CA potentiel: {formatCurrency(pipeline.total_value)} • CA pondéré: {formatCurrency(pipeline.weighted_value)}</p></div>
        <Button onClick={()=>setShowCreate(true)}><Plus className="w-4 h-4 mr-1"/>Nouvelle opportunité</Button>
      </div>

      {alerts.length>0 && (
        <Card className="border-amber-200 bg-amber-50 dark:bg-amber-950/20"><CardContent className="pt-3 flex gap-2"><AlertTriangle className="w-4 h-4 text-amber-600 mt-0.5"/><div className="text-sm"><div className="font-medium text-amber-800 dark:text-amber-200">{alerts.length} alerte(s) : affaires bloquées ou en retard</div><ul className="list-disc ml-4 text-amber-700 dark:text-amber-300">{alerts.slice(0,5).map((a:any,i:number)=><li key={i}>{a.title}: {a.message}</li>)}</ul></div></CardContent></Card>
      )}

      <Card><CardContent className="pt-4 flex gap-3">
        <div className="flex-1 relative"><Search className="w-4 h-4 absolute left-3 top-3 text-muted-foreground"/><Input className="pl-9" placeholder="Filtrer par titre ou client..." value={search} onChange={e=>setSearch(e.target.value)} /></div>
        <div className="text-xs text-muted-foreground hidden sm:flex items-center gap-2"><Filter className="w-3 h-3"/>Filtrez aussi par commercial/source depuis l'admin</div>
      </CardContent></Card>

      {showCreate && (
        <Card><CardContent className="pt-6">
          <form onSubmit={createOpp} className="grid grid-cols-1 md:grid-cols-4 gap-3">
            <div><label className="text-xs">Titre *</label><Input value={form.title} onChange={e=>setForm({...form, title:e.target.value})} required /></div>
            <div><label className="text-xs">Client *</label><Select value={form.client_id} onChange={e=>setForm({...form, client_id:e.target.value})} required><option value="">Sélectionner</option>{clients.map((c:any)=><option key={c.id} value={c.id}>{c.company_name}</option>)}</Select></div>
            <div><label className="text-xs">Étape *</label><Select value={form.stage_id} onChange={e=>setForm({...form, stage_id:e.target.value})} required><option value="">Sélectionner</option>{pipeline.stages.map((s:any)=><option key={s.id} value={s.id}>{s.name}</option>)}</Select></div>
            <div><label className="text-xs">Montant (TND)</label><Input type="number" value={form.amount} onChange={e=>setForm({...form, amount:e.target.value})} /></div>
            <div><label className="text-xs">Probabilité %</label><Input type="number" min="0" max="100" value={form.probability} onChange={e=>setForm({...form, probability:e.target.value})} /></div>
            <div><label className="text-xs">Échéance</label><Input type="date" value={form.expected_close_date} onChange={e=>setForm({...form, expected_close_date:e.target.value})} /></div>
            <div><label className="text-xs">Source</label><Input value={form.source} onChange={e=>setForm({...form, source:e.target.value})} placeholder="Site web, Salon..." /></div>
            <div><label className="text-xs">Prochaine action</label><Input value={form.next_action} onChange={e=>setForm({...form, next_action:e.target.value})} /></div>
            <div className="flex gap-2 items-end"><Button type="submit">Créer</Button><Button type="button" variant="outline" onClick={()=>setShowCreate(false)}>Annuler</Button></div>
          </form>
        </CardContent></Card>
      )}

      <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={onDragEnd}>
        <div className="flex gap-4 overflow-x-auto pb-4 scrollbar-thin">
          {pipeline.stages.map((stage:any)=>{
            const opps = filtered.filter((o:any)=>o.stage_id===stage.id)
            const val = opps.reduce((s:any,o:any)=>s+(o.amount||0),0)
            return <DroppableColumn key={stage.id} stage={stage} count={opps.length} value={val}>{opps.map((opp:any)=><DraggableCard key={opp.id} opp={opp} onClick={()=>{/* could open modal */}} />)}{opps.length===0 && <div className="text-xs text-muted-foreground text-center py-6">Aucune affaire</div>}</DroppableColumn>
          })}
        </div>
      </DndContext>

      {movingOpp && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <Card className="w-full max-w-md"><CardHeader><CardTitle className="text-sm">Raison de perte obligatoire</CardTitle></CardHeader><CardContent className="space-y-3"><p className="text-sm">L'opportunité "{movingOpp.title}" va passer en "Perdu". Veuillez saisir la raison :</p><Input placeholder="Ex: Budget insuffisant, concurrent moins cher..." value={lossReason} onChange={e=>setLossReason(e.target.value)} /><div className="flex gap-2"><Button onClick={confirmMove}>Confirmer</Button><Button variant="outline" onClick={()=>setMovingOpp(null)}>Annuler</Button></div></CardContent></Card>
        </div>
      )}
    </div>
  )
}
