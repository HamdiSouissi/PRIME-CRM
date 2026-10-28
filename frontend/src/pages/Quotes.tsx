import { useEffect, useState } from 'react'
import { api } from '../api/client'
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card'
import { Button } from '../components/ui/button'
import { Input, Textarea } from '../components/ui/input'
import { formatCurrency, formatDate } from '../lib/utils'
import { Plus, Eye, Copy, Trash2, FileText, Download } from 'lucide-react'
import { toast } from 'sonner'

export function Quotes() {
  const [quotes, setQuotes] = useState<any[]>([])
  const [clients, setClients] = useState<any[]>([])
  const [products, setProducts] = useState<any[]>([])
  const [showCreate, setShowCreate] = useState(false)
  const [filter, setFilter] = useState('')
  const [form, setForm] = useState({ client_id:'', title:'', valid_until:'', notes:'', terms:'', currency:'TND', discount_percent:'0' })
  const [lines, setLines] = useState<any[]>([{ name:'', quantity:'1', unit_price:'0', discount_percent:'0', tax_rate:'19', unit:'pièce' }])
  const [preview, setPreview] = useState<any>(null)

  const load = () => { api.get(`/quotes${filter ? `?status=${filter}`:''}`).then(r=>setQuotes(r.data)); api.get('/clients?page=1&page_size=100').then(r=>setClients(r.data.items)); api.get('/products').then(r=>setProducts(r.data)) }
  useEffect(()=>{ load() }, [filter])

  const create = async (e: React.FormEvent) => {
    e.preventDefault()
    try {
      const payload = { ...form, client_id: Number(form.client_id), discount_percent: Number(form.discount_percent), valid_until: form.valid_until || null, lines: lines.filter(l=>l.name).map(l=>({...l, quantity:Number(l.quantity), unit_price:Number(l.unit_price), discount_percent:Number(l.discount_percent), tax_rate:Number(l.tax_rate)})) }
      const res = await api.post('/quotes', payload)
      toast.success(`Devis ${res.data.number} créé`)
      setShowCreate(false); load()
    } catch(e:any){ toast.error(e.response?.data?.detail||'Erreur') }
  }
  const addLine = () => setLines([...lines, { name:'', quantity:'1', unit_price:'0', discount_percent:'0', tax_rate:'19', unit:'pièce' }])
  const updateLine = (idx:number, field:string, val:string) => { const n=[...lines]; n[idx][field]=val; setLines(n) }
  const pickProduct = (idx:number, pid:string) => {
    const p = products.find((x:any)=>String(x.id)===pid)
    if (p) { const n=[...lines]; n[idx]={...n[idx], name:p.name, unit_price:String(p.price), tax_rate:String(p.tax_rate), unit:p.unit, product_id:p.id}; setLines(n) }
  }

  const openPreview = async (id:number) => {
    const res = await api.get(`/quotes/${id}`)
    setPreview(res.data)
  }

  return (
    <div className="p-4 lg:p-8 max-w-[1600px] mx-auto space-y-4">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div><h1 className="text-2xl font-bold">Devis</h1><p className="text-sm text-muted-foreground">Catalogue produits, remises, TVA configurables, numérotation automatique, PDF professionnels</p></div>
        <div className="flex gap-2">
          <select value={filter} onChange={e=>setFilter(e.target.value)} className="h-9 rounded-md border px-3 text-sm"><option value="">Tous les statuts</option><option value="draft">Brouillon</option><option value="sent">Envoyé</option><option value="accepted">Accepté</option><option value="refused">Refusé</option><option value="expired">Expiré</option></select>
          <Button onClick={()=>setShowCreate(true)}><Plus className="w-4 h-4 mr-1"/>Nouveau devis</Button>
        </div>
      </div>

      {showCreate && (
        <Card><CardContent className="pt-6 space-y-4">
          <form onSubmit={create} className="space-y-4">
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
              <div><label className="text-xs font-medium">Client *</label><select value={form.client_id} onChange={e=>setForm({...form, client_id:e.target.value})} required className="h-10 w-full rounded-md border px-2 text-sm"><option value="">Sélectionner</option>{clients.map((c:any)=><option key={c.id} value={c.id}>{c.company_name}</option>)}</select></div>
              <div><label className="text-xs">Titre *</label><Input value={form.title} onChange={e=>setForm({...form, title:e.target.value})} required placeholder="Prestation développement" /></div>
              <div><label className="text-xs">Validité</label><Input type="date" value={form.valid_until} onChange={e=>setForm({...form, valid_until:e.target.value})} /></div>
              <div><label className="text-xs">Devise</label><select value={form.currency} onChange={e=>setForm({...form, currency:e.target.value})} className="h-10 w-full rounded-md border px-2 text-sm"><option value="TND">TND (Dinar Tunisien)</option><option value="EUR">EUR</option><option value="USD">USD</option></select></div>
              <div><label className="text-xs">Remise globale %</label><Input type="number" value={form.discount_percent} onChange={e=>setForm({...form, discount_percent:e.target.value})} /></div>
            </div>

            <div>
              <div className="flex items-center justify-between mb-2"><span className="text-sm font-medium">Lignes</span><Button type="button" size="sm" variant="outline" onClick={addLine}><Plus className="w-3 h-3 mr-1"/>Ajouter ligne</Button></div>
              <div className="space-y-2">
                <div className="hidden md:grid grid-cols-12 gap-2 text-xs text-muted-foreground px-1"><div className="col-span-3">Produit / Désignation</div><div className="col-span-2">Qté / Unité</div><div className="col-span-2">P.U. HT</div><div className="col-span-2">Remise % / TVA %</div><div className="col-span-3">Actions</div></div>
                {lines.map((l:any,i:number)=>(
                  <div key={i} className="grid grid-cols-12 gap-2 items-end border rounded-lg p-2">
                    <div className="col-span-12 md:col-span-3">
                      <select value={l.product_id || ''} onChange={e=>pickProduct(i, e.target.value)} className="h-8 w-full rounded border px-1 text-xs mb-1"><option value="">-- Catalogue --</option>{products.map((p:any)=><option key={p.id} value={p.id}>{p.name} ({p.price} {p.currency || 'TND'})</option>)}</select>
                      <Input placeholder="Désignation" value={l.name} onChange={e=>updateLine(i,'name',e.target.value)} className="h-8 text-sm" />
                    </div>
                    <div className="col-span-6 md:col-span-2 flex gap-1"><Input type="number" placeholder="Qté" value={l.quantity} onChange={e=>updateLine(i,'quantity',e.target.value)} className="h-8"/><Input value={l.unit} onChange={e=>updateLine(i,'unit',e.target.value)} className="h-8 w-16" placeholder="pièce"/></div>
                    <div className="col-span-6 md:col-span-2"><Input type="number" value={l.unit_price} onChange={e=>updateLine(i,'unit_price',e.target.value)} className="h-8"/></div>
                    <div className="col-span-6 md:col-span-2 flex gap-1"><Input type="number" placeholder="Rem %" value={l.discount_percent} onChange={e=>updateLine(i,'discount_percent',e.target.value)} className="h-8"/><Input type="number" placeholder="TVA" value={l.tax_rate} onChange={e=>updateLine(i,'tax_rate',e.target.value)} className="h-8"/></div>
                    <div className="col-span-6 md:col-span-3 flex gap-1"><span className="text-xs text-muted-foreground flex-1">{ (Number(l.quantity||0)*Number(l.unit_price||0)*(1-Number(l.discount_percent||0)/100)*(1+Number(l.tax_rate||0)/100)).toFixed(2)} {form.currency}</span><Button type="button" size="sm" variant="ghost" onClick={()=>setLines(lines.filter((_,idx)=>idx!==i))}>✕</Button></div>
                  </div>
                ))}
              </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <div><label className="text-xs">Notes</label><Textarea value={form.notes} onChange={e=>setForm({...form, notes:e.target.value})} rows={2} placeholder="Notes internes..." /></div>
              <div><label className="text-xs">Conditions de paiement</label><Textarea value={form.terms} onChange={e=>setForm({...form, terms:e.target.value})} rows={2} placeholder="Paiement à 30 jours, validité 30 jours..." /></div>
            </div>
            <div className="flex gap-2"><Button type="submit">Créer le devis</Button><Button type="button" variant="outline" onClick={()=>setShowCreate(false)}>Annuler</Button></div>
          </form>
        </CardContent></Card>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
        {quotes.map((q:any)=>(
          <Card key={q.id} className="hover:shadow-md">
            <CardContent className="pt-4">
              <div className="flex items-start justify-between">
                <div><div className="font-bold text-sm">{q.number}</div><div className="font-medium text-sm">{q.title}</div><div className="text-xs text-muted-foreground">{q.client_name} • {formatDate(q.created_at)} • Échéance {formatDate(q.valid_until)}</div></div>
                <span className={`text-xs px-2 py-1 rounded-full ${q.status==='draft' ? 'bg-slate-100' : q.status==='sent' ? 'bg-sky-100 text-sky-700' : q.status==='accepted' ? 'bg-green-100 text-green-700' : q.status==='refused' ? 'bg-red-100 text-red-700' : 'bg-amber-100 text-amber-700'}`}>{q.status}</span>
              </div>
              <div className="text-right mt-2"><div className="text-lg font-bold">{formatCurrency(q.total, q.currency)}</div><div className="text-xs text-muted-foreground">HT: {formatCurrency(q.subtotal, q.currency)} + TVA {formatCurrency(q.tax_amount, q.currency)}</div></div>
              <div className="flex gap-1 mt-3">
                <Button size="sm" variant="outline" onClick={()=>openPreview(q.id)}><Eye className="w-3 h-3 mr-1"/>Aperçu</Button>
                <a href={`${api.defaults.baseURL}/quotes/${q.id}/pdf`} target="_blank" className="flex-1"><Button size="sm" variant="outline" className="w-full"><Download className="w-3 h-3 mr-1"/>PDF</Button></a>
                <Button size="sm" variant="ghost" onClick={async()=>{ const r=await api.post(`/quotes/${q.id}/duplicate`); toast.success('Dupliqué'); load()}}><Copy className="w-3 h-3"/></Button>
              </div>
              <div className="flex gap-1 mt-2">
                <select value={q.status} onChange={async e=>{ await api.put(`/quotes/${q.id}`, { status: e.target.value }); load() }} className="flex-1 h-8 rounded border px-1 text-xs"><option value="draft">Brouillon</option><option value="sent">Envoyé</option><option value="accepted">Accepté</option><option value="refused">Refusé</option><option value="expired">Expiré</option></select>
                <Button size="sm" variant="ghost" onClick={async()=>{ if(!confirm('Supprimer ?')) return; await api.delete(`/quotes/${q.id}`); load()}}><Trash2 className="w-3 h-3"/></Button>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
      {quotes.length===0 && <div className="text-center py-12 text-muted-foreground"><FileText className="w-12 h-12 mx-auto mb-3 opacity-30"/><p>Aucun devis — Créez votre premier devis professionnel en PDF</p></div>}

      {preview && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <Card className="w-full max-w-3xl max-h-[90vh] overflow-auto">
            <CardHeader><CardTitle className="text-sm">{preview.number} — {preview.title} <span className="text-muted-foreground font-normal">({preview.status})</span></CardTitle></CardHeader>
            <CardContent className="space-y-3">
              <div className="text-sm grid grid-cols-2 gap-2"><div>Client: {preview.client_name}</div><div>Devise: {preview.currency}</div><div>Sous-total HT: {formatCurrency(preview.subtotal, preview.currency)}</div><div>Remise: -{formatCurrency(preview.discount_amount, preview.currency)}</div><div>TVA: {formatCurrency(preview.tax_amount, preview.currency)}</div><div className="font-bold">Total TTC: {formatCurrency(preview.total, preview.currency)}</div></div>
              <div className="overflow-x-auto"><table className="w-full text-xs border"><thead><tr className="bg-slate-50"><th className="p-2 text-left">Désignation</th><th className="p-2">Qté</th><th className="p-2">P.U. HT</th><th className="p-2">TVA</th><th className="p-2">Total TTC</th></tr></thead><tbody>{preview.lines.map((l:any)=><tr key={l.id} className="border-t"><td className="p-2">{l.name}</td><td className="p-2 text-center">{l.quantity} {l.unit}</td><td className="p-2 text-right">{formatCurrency(l.unit_price, preview.currency)}</td><td className="p-2 text-center">{l.tax_rate}%</td><td className="p-2 text-right">{formatCurrency(l.line_total, preview.currency)}</td></tr>)}</tbody></table></div>
              {preview.notes && <div className="text-xs">Notes: {preview.notes}</div>}
              {preview.terms && <div className="text-xs">Conditions: {preview.terms}</div>}
              <div className="flex gap-2"><a href={`${api.defaults.baseURL}/quotes/${preview.id}/pdf`} target="_blank"><Button><Download className="w-4 h-4 mr-1"/>Télécharger PDF</Button></a><Button variant="outline" onClick={()=>setPreview(null)}>Fermer</Button></div>
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  )
}
