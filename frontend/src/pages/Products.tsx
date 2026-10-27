import { useEffect, useState } from 'react'
import { api } from '../api/client'
import { Card, CardContent } from '../components/ui/card'
import { Button } from '../components/ui/button'
import { Input } from '../components/ui/input'
import { Package, Plus, Trash2 } from 'lucide-react'
import { formatCurrency } from '../lib/utils'
import { toast } from 'sonner'

export function Products() {
  const [products, setProducts] = useState<any[]>([])
  const [show, setShow] = useState(false)
  const [form, setForm] = useState({ name:'', sku:'', category:'', price:'', cost:'', tax_rate:'19', unit:'pièce', description:'' })
  const [search, setSearch] = useState('')

  const load = () => api.get(`/products${search ? `?search=${search}` : ''}`).then(r=>setProducts(r.data))
  useEffect(()=>{ load() }, [])
  useEffect(()=>{ const t=setTimeout(load,400); return ()=>clearTimeout(t)}, [search])

  const create = async (e: React.FormEvent) => {
    e.preventDefault()
    try { await api.post('/products', {...form, price: Number(form.price), cost: form.cost ? Number(form.cost) : null, tax_rate: Number(form.tax_rate)}); toast.success('Produit créé'); setShow(false); setForm({name:'', sku:'', category:'', price:'', cost:'', tax_rate:'19', unit:'pièce', description:''}); load() } catch(e:any){ toast.error('Erreur')}
  }

  return (
    <div className="p-4 lg:p-8 max-w-[1600px] mx-auto space-y-4">
      <div className="flex items-center justify-between"><div><h1 className="text-2xl font-bold">Produits & Services</h1><p className="text-sm text-muted-foreground">Catalogue avec prix, coûts, TVA et marges estimées</p></div><Button onClick={()=>setShow(true)}><Plus className="w-4 h-4 mr-1"/>Nouveau</Button></div>
      <Card><CardContent className="pt-4 flex gap-3"><Input placeholder="Rechercher produit, SKU..." value={search} onChange={e=>setSearch(e.target.value)} className="flex-1" /></CardContent></Card>
      {show && <Card><CardContent className="pt-6"><form onSubmit={create} className="grid grid-cols-1 md:grid-cols-4 gap-3">
        <div><label className="text-xs">Nom *</label><Input value={form.name} onChange={e=>setForm({...form, name:e.target.value})} required /></div>
        <div><label className="text-xs">SKU</label><Input value={form.sku} onChange={e=>setForm({...form, sku:e.target.value})} placeholder="PRD-001" /></div>
        <div><label className="text-xs">Catégorie</label><Input value={form.category} onChange={e=>setForm({...form, category:e.target.value})} /></div>
        <div><label className="text-xs">Unité</label><select value={form.unit} onChange={e=>setForm({...form, unit:e.target.value})} className="h-10 w-full rounded-md border px-2 text-sm"><option>pièce</option><option>heure</option><option>jour</option><option>forfait</option><option>kg</option><option>m²</option></select></div>
        <div><label className="text-xs">Prix unitaire</label><Input type="number" value={form.price} onChange={e=>setForm({...form, price:e.target.value})} required /></div>
        <div><label className="text-xs">Coût (pour marge)</label><Input type="number" value={form.cost} onChange={e=>setForm({...form, cost:e.target.value})} /></div>
        <div><label className="text-xs">TVA %</label><Input type="number" value={form.tax_rate} onChange={e=>setForm({...form, tax_rate:e.target.value})} /></div>
        <div><label className="text-xs">Description</label><Input value={form.description} onChange={e=>setForm({...form, description:e.target.value})} /></div>
        <div className="flex gap-2 items-end"><Button type="submit">Créer</Button><Button type="button" variant="outline" onClick={()=>setShow(false)}>Annuler</Button></div>
      </form></CardContent></Card>}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {products.map((p:any)=>(
          <Card key={p.id}><CardContent className="pt-4">
            <div className="flex items-start justify-between"><div className="flex gap-3"><div className="w-10 h-10 rounded-lg bg-sky-50 flex items-center justify-center"><Package className="w-5 h-5 text-sky-600"/></div><div><div className="font-medium text-sm">{p.name}</div><div className="text-xs text-muted-foreground">{p.sku || ''} • {p.category || ''}</div></div></div><Button size="sm" variant="ghost" onClick={async()=>{ if(!confirm('Supprimer ?')) return; await api.delete(`/products/${p.id}`); load()}}><Trash2 className="w-3 h-3"/></Button></div>
            <div className="mt-3 flex justify-between items-end"><div><div className="text-lg font-bold">{formatCurrency(p.price)}</div><div className="text-xs text-muted-foreground">Coût: {p.cost ? formatCurrency(p.cost) : '—'} • Marge: {p.cost ? formatCurrency(p.price - p.cost) + ` (${(((p.price - p.cost)/p.price)*100).toFixed(0)}%)` : '—'}</div></div><span className="text-xs px-2 py-1 rounded bg-slate-100">{p.tax_rate}% TVA</span></div>
          </CardContent></Card>
        ))}
      </div>
      {products.length===0 && <div className="text-center py-12 text-muted-foreground">Aucun produit — Créez votre catalogue pour l'utiliser dans les devis</div>}
    </div>
  )
}
