import { useEffect, useState } from 'react'
import { api } from '../api/client'
import { Card, CardContent } from '../components/ui/card'
import { Button } from '../components/ui/button'
import { Input, Select, Badge } from '../components/ui/input'
import { Link } from 'react-router-dom'
import { Search, Plus, Upload, Download, Filter, Users2, Building2, Trash2, Eye } from 'lucide-react'
import { toast } from 'sonner'

export function Clients() {
  const [data, setData] = useState<any>(null)
  const [search, setSearch] = useState('')
  const [type, setType] = useState('')
  const [sector, setSector] = useState('')
  const [page, setPage] = useState(1)
  const [showCreate, setShowCreate] = useState(false)
  const [form, setForm] = useState({ company_name: '', email: '', phone: '', city: '', sector: '', source: '', type: 'prospect' })
  const [duplicates, setDuplicates] = useState<any[]>([])
  const [users, setUsers] = useState<any[]>([])

  const load = () => {
    const params = new URLSearchParams({ page: String(page), page_size: '12' })
    if (search) params.set('search', search)
    if (type) params.set('type', type)
    if (sector) params.set('sector', sector)
    api.get(`/clients?${params}`).then(r=>setData(r.data))
    api.get('/clients/duplicates').then(r=>setDuplicates(r.data)).catch(()=>{})
  }
  useEffect(()=>{ load() }, [page, type, sector])
  useEffect(()=>{ const t=setTimeout(load, 400); return ()=>clearTimeout(t) }, [search])
  useEffect(()=>{ api.get('/users').then(r=>setUsers(r.data)).catch(()=>{}) }, [])

  const create = async (e: React.FormEvent) => {
    e.preventDefault()
    try { await api.post('/clients', form); toast.success('Client créé'); setShowCreate(false); setForm({company_name:'', email:'', phone:'', city:'', sector:'', source:'', type:'prospect'}); load() } catch(e:any){ toast.error(e.response?.data?.detail||'Erreur') }
  }

  const handleImport = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    const fd = new FormData(); fd.append('file', file)
    // preview first
    try {
      const preview = await api.post('/import-export/clients/preview', fd, { headers: {'Content-Type':'multipart/form-data'}})
      if (preview.data.errors?.length) toast.error(`${preview.data.total_errors} erreurs détectées`)
      if (!confirm(`Importer ${preview.data.total_rows} lignes ?\n${preview.data.errors?.length ? preview.data.errors[0].error : ''}`)) return
      const res = await api.post('/import-export/clients/import', fd, { headers: {'Content-Type':'multipart/form-data'}})
      toast.success(`${res.data.imported} importés`)
      load()
    } catch(err:any){ toast.error(err.response?.data?.detail||'Erreur import') }
  }

  return (
    <div className="p-4 lg:p-8 max-w-[1600px] mx-auto space-y-4">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div><h1 className="text-2xl font-bold">Clients & Prospects</h1><p className="text-sm text-muted-foreground">Gérez votre base clients avec recherche, filtres, import/export et détection de doublons</p></div>
        <div className="flex gap-2 flex-wrap">
          <label className="px-3 py-2 border rounded-md text-sm cursor-pointer hover:bg-accent flex items-center gap-2"><Upload className="w-4 h-4"/>Importer CSV/Excel<input type="file" className="hidden" accept=".csv,.xlsx,.xls" onChange={handleImport} /></label>
          <a href={`${api.defaults.baseURL}/import-export/clients/export?format=csv`} className="px-3 py-2 border rounded-md text-sm flex items-center gap-2 hover:bg-accent"><Download className="w-4 h-4"/>Exporter CSV</a>
          <a href={`${api.defaults.baseURL}/import-export/clients/export?format=excel`} className="px-3 py-2 border rounded-md text-sm flex items-center gap-2 hover:bg-accent"><Download className="w-4 h-4"/>Excel</a>
          <Button onClick={()=>setShowCreate(true)}><Plus className="w-4 h-4 mr-1"/>Nouveau</Button>
        </div>
      </div>

      {duplicates.length>0 && (
        <Card className="border-amber-200 bg-amber-50 dark:bg-amber-950/20"><CardContent className="pt-4"><div className="font-medium text-sm text-amber-800 dark:text-amber-200">Doublons détectés: {duplicates.length}</div><div className="mt-2 space-y-2">{duplicates.slice(0,3).map((d:any,i:number)=><div key={i} className="text-xs bg-white dark:bg-slate-900 p-2 rounded border flex justify-between items-center"><span>{d.reason} — {d.group.map((g:any)=>g.company_name).join(' / ')}</span><Button size="sm" variant="outline" className="text-xs" onClick={async()=>{ if(!confirm('Fusionner ?')) return; await api.post('/clients/merge', {target_id:d.group[0].id, source_ids: d.group.slice(1).map((g:any)=>g.id)}); toast.success('Fusionné'); load() }}>Fusionner</Button></div>)}</div></CardContent></Card>
      )}

      <Card><CardContent className="pt-4 flex flex-col sm:flex-row gap-3">
        <div className="flex-1 relative"><Search className="w-4 h-4 absolute left-3 top-3 text-muted-foreground"/><Input className="pl-9" placeholder="Rechercher par nom, email, ville, téléphone..." value={search} onChange={e=>setSearch(e.target.value)} /></div>
        <select value={type} onChange={e=>setType(e.target.value)} className="h-10 rounded-md border border-input bg-background px-3 text-sm"><option value="">Tous les types</option><option value="prospect">Prospect</option><option value="client">Client</option><option value="partenaire">Partenaire</option></select>
        <Input placeholder="Secteur..." value={sector} onChange={e=>setSector(e.target.value)} className="sm:w-40" />
        <Button variant="outline" onClick={()=>{setSearch(''); setType(''); setSector(''); setPage(1)}}><Filter className="w-4 h-4 mr-1"/>Réinitialiser</Button>
      </CardContent></Card>

      {showCreate && (
        <Card><CardContent className="pt-6">
          <form onSubmit={create} className="grid grid-cols-1 md:grid-cols-3 gap-3">
            <div><label className="text-xs font-medium">Société *</label><Input value={form.company_name} onChange={e=>setForm({...form, company_name:e.target.value})} required /></div>
            <div><label className="text-xs">Email</label><Input value={form.email} onChange={e=>setForm({...form, email:e.target.value})} /></div>
            <div><label className="text-xs">Téléphone</label><Input value={form.phone} onChange={e=>setForm({...form, phone:e.target.value})} /></div>
            <div><label className="text-xs">Ville</label><Input value={form.city} onChange={e=>setForm({...form, city:e.target.value})} /></div>
            <div><label className="text-xs">Secteur</label><Input value={form.sector} onChange={e=>setForm({...form, sector:e.target.value})} placeholder="Technologie, Industrie..." /></div>
            <div><label className="text-xs">Source</label><Input value={form.source} onChange={e=>setForm({...form, source:e.target.value})} placeholder="Site web, Salon..." /></div>
            <div><label className="text-xs">Type</label><Select value={form.type} onChange={e=>setForm({...form, type:e.target.value})}><option value="prospect">Prospect</option><option value="client">Client</option><option value="partenaire">Partenaire</option></Select></div>
            <div className="flex gap-2 items-end"><Button type="submit">Créer</Button><Button type="button" variant="outline" onClick={()=>setShowCreate(false)}>Annuler</Button></div>
          </form>
        </CardContent></Card>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
        {data?.items?.map((c:any)=>(
          <Card key={c.id} className="hover:shadow-md transition-shadow">
            <CardContent className="pt-4">
              <div className="flex items-start justify-between">
                <div className="flex gap-3">
                  <div className="w-10 h-10 rounded-lg bg-slate-100 dark:bg-slate-800 flex items-center justify-center"><Building2 className="w-5 h-5 text-slate-600" /></div>
                  <div><div className="font-semibold text-sm">{c.company_name}</div><div className="text-xs text-muted-foreground">{c.email || '—'} • {c.phone || '—'}</div><div className="text-xs text-muted-foreground">{c.city || ''} {c.sector ? `• ${c.sector}` : ''}</div></div>
                </div>
                <Badge variant={c.type==='client' ? 'default' : 'secondary'}>{c.type}</Badge>
              </div>
              <div className="flex gap-1 mt-3">
                <Link to={`/clients/${c.id}`} className="flex-1"><Button size="sm" variant="outline" className="w-full"><Eye className="w-3 h-3 mr-1"/>Voir 360°</Button></Link>
                <Button size="sm" variant="ghost" onClick={async()=>{ if(!confirm('Archiver ce client ?')) return; await api.post(`/clients/${c.id}/archive`); load(); }}><Trash2 className="w-3 h-3"/></Button>
              </div>
              {c.owner_name && <div className="text-xs text-muted-foreground mt-2">Propriétaire: {c.owner_name}</div>}
            </CardContent>
          </Card>
        ))}
      </div>
      {data?.items?.length===0 && <div className="text-center py-12 text-muted-foreground"><Users2 className="w-12 h-12 mx-auto mb-3 opacity-30"/><p>Aucun client trouvé</p><p className="text-xs">Créez votre premier prospect ou importez depuis CSV/Excel</p></div>}

      {data && data.pages>1 && (
        <div className="flex justify-center gap-2">
          <Button variant="outline" disabled={page===1} onClick={()=>setPage(p=>p-1)}>Précédent</Button>
          <span className="px-3 py-2 text-sm">Page {data.page} / {data.pages} ({data.total} résultats)</span>
          <Button variant="outline" disabled={page>=data.pages} onClick={()=>setPage(p=>p+1)}>Suivant</Button>
        </div>
      )}
    </div>
  )
}
