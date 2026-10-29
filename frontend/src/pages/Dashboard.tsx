import { useEffect, useState } from 'react'
import { api, API_DOCS_URL } from '../api/client'
import { Card, CardHeader, CardTitle, CardContent } from '../components/ui/card'
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, PieChart, Pie, Cell, LineChart, Line } from 'recharts'
import { Users, TrendingUp, FileText, AlertTriangle, ArrowUpRight, Briefcase, Clock, CheckCircle2 } from 'lucide-react'
import { formatCurrency } from '../lib/utils'
import { Link } from 'react-router-dom'

const COLORS = ['#0ea5e9', '#8b5cf6', '#f59e0b', '#ec4899', '#22c55e', '#ef4444', '#06b6d4', '#f97316']

export function Dashboard() {
  const [data, setData] = useState<any>(null)
  const [loading, setLoading] = useState(true)
  const [period, setPeriod] = useState('month')

  useEffect(() => {
    setLoading(true)
    api.get(`/dashboard?period=${period}`).then(r => setData(r.data)).finally(() => setLoading(false))
  }, [period])

  if (loading) return <div className="p-8">Chargement du tableau de bord...</div>
  if (!data) return <div className="p-8">Erreur de chargement</div>
  const s = data.stats

  const kpis = [
    { label: 'Prospects', value: s.prospects_count, icon: Users, color: 'bg-sky-500', sub: `${s.clients_count} clients` },
    { label: 'Pipeline', value: formatCurrency(s.pipeline_value), icon: Briefcase, color: 'bg-violet-500', sub: `Pondéré: ${formatCurrency(s.weighted_pipeline_value)}` },
    { label: 'CA signé', value: formatCurrency(s.signed_revenue), icon: TrendingUp, color: 'bg-emerald-500', sub: `Prévisionnel: ${formatCurrency(s.forecast_revenue)}` },
    { label: 'Taux conversion', value: `${s.conversion_rate}%`, icon: CheckCircle2, color: 'bg-amber-500', sub: `${s.opportunities_won} gagnées / ${s.opportunities_lost} perdues` },
    { label: 'Tâches retard', value: s.overdue_tasks, icon: AlertTriangle, color: 'bg-red-500', sub: `${s.upcoming_meetings} RDV à venir` },
    { label: 'Devis', value: s.quotes_created, icon: FileText, color: 'bg-blue-500', sub: `${s.quotes_accepted} acceptés • ${s.quotes_refused} refusés` },
  ]

  return (
    <div className="p-4 lg:p-8 space-y-6 max-w-[1600px] mx-auto">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold">Tableau de bord</h1>
          <p className="text-muted-foreground text-sm">Vue d'ensemble de votre activité commerciale • <span className="text-xs">CA signé = affaires gagnées • CA prévisionnel = pondéré + signé</span></p>
        </div>
        <div className="flex items-center gap-2">
          <select value={period} onChange={e=>setPeriod(e.target.value)} className="h-9 rounded-md border border-input bg-background px-3 text-sm">
            <option value="week">7 derniers jours</option>
            <option value="month">Ce mois</option>
            <option value="quarter">Ce trimestre</option>
            <option value="year">Cette année</option>
            <option value="all">Tout</option>
          </select>
          <a href={`${api.defaults.baseURL}/dashboard/export?format=csv`} className="text-xs px-3 py-2 border rounded-md hover:bg-accent" target="_blank">Exporter CSV</a>
        </div>
      </div>

      {data.alerts?.length > 0 && (
        <Card className="border-amber-200 bg-amber-50 dark:bg-amber-950/30">
          <CardContent className="pt-4 flex gap-2 flex-wrap">
            <AlertTriangle className="w-4 h-4 text-amber-600 mt-0.5" />
            <div className="text-sm">
              <div className="font-medium text-amber-800 dark:text-amber-200">{data.alerts.length} alerte(s)</div>
              <ul className="list-disc ml-4 text-amber-700 dark:text-amber-300">
                {data.alerts.map((a:any,i:number)=><li key={i}>{a.message}</li>)}
              </ul>
            </div>
          </CardContent>
        </Card>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
        {kpis.map(k=>(
          <Card key={k.label} className="hover:shadow-md transition-shadow">
            <CardContent className="pt-6 flex items-start justify-between">
              <div>
                <div className="text-xs text-muted-foreground uppercase tracking-wide">{k.label}</div>
                <div className="text-2xl font-bold mt-1">{k.value}</div>
                <div className="text-xs text-muted-foreground mt-1">{k.sub}</div>
              </div>
              <div className={`w-10 h-10 rounded-xl ${k.color} flex items-center justify-center text-white`}><k.icon className="w-5 h-5" /></div>
            </CardContent>
          </Card>
        ))}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card>
          <CardHeader><CardTitle className="text-sm">Pipeline par étape</CardTitle></CardHeader>
          <CardContent>
            <ResponsiveContainer width="100%" height={280}>
              <BarChart data={data.pipeline_by_stage}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="name" fontSize={10} interval={0} angle={-20} textAnchor="end" height={60} />
                <YAxis fontSize={12} />
                <Tooltip formatter={(v:any)=>formatCurrency(v as number)} />
                <Bar dataKey="value" fill="#0ea5e9" radius={[6,6,0,0]} />
              </BarChart>
            </ResponsiveContainer>
            <div className="grid grid-cols-3 gap-2 mt-2 text-xs">
              {data.pipeline_by_stage.map((p:any)=><div key={p.name} className="text-center"><div className="font-medium">{p.count} affaires</div><div className="text-muted-foreground truncate">{p.name}</div></div>)}
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader><CardTitle className="text-sm">Chiffre d'affaires (6 derniers mois)</CardTitle></CardHeader>
          <CardContent>
            <ResponsiveContainer width="100%" height={260}>
              <LineChart data={data.revenue_by_month}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="month" fontSize={12} />
                <YAxis fontSize={12} />
                <Tooltip />
                <Line type="monotone" dataKey="revenue" stroke="#22c55e" strokeWidth={3} dot={{r:4}} />
              </LineChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>

        <Card>
          <CardHeader><CardTitle className="text-sm">Répartition par source</CardTitle></CardHeader>
          <CardContent>
            <ResponsiveContainer width="100%" height={250}>
              <PieChart>
                <Pie data={data.opportunities_by_source} dataKey="value" nameKey="name" cx="50%" cy="50%" outerRadius={90} label={({name, percent})=>`${name} ${(percent*100).toFixed(0)}%`}>
                  {data.opportunities_by_source.map((_:any, i:number)=><Cell key={i} fill={COLORS[i % COLORS.length]} />)}
                </Pie>
                <Tooltip formatter={(v:any)=>formatCurrency(v as number)} />
              </PieChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between"><CardTitle className="text-sm">Performance par commercial</CardTitle><Link to="/pipeline" className="text-xs text-sky-600 hover:underline">Voir pipeline</Link></CardHeader>
          <CardContent>
            <div className="space-y-3">
              {data.performance_by_owner.map((p:any)=>(
                <div key={p.owner} className="flex items-center justify-between p-3 rounded-lg bg-slate-50 dark:bg-slate-900">
                  <div><div className="font-medium text-sm">{p.owner}</div><div className="text-xs text-muted-foreground">{p.opportunities} affaires • {p.won} gagnées</div></div>
                  <div className="text-right"><div className="font-bold text-sm">{formatCurrency(p.revenue)}</div><div className="text-xs text-muted-foreground">Pipeline {formatCurrency(p.pipeline)}</div></div>
                </div>
              ))}
              {data.performance_by_owner.length===0 && <div className="text-sm text-muted-foreground text-center py-6">Aucun commercial</div>}
            </div>
          </CardContent>
        </Card>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card>
          <CardHeader><CardTitle className="text-sm flex items-center gap-2"><Clock className="w-4 h-4" /> Activités récentes</CardTitle></CardHeader>
          <CardContent>
            <div className="space-y-2">
              {data.recent_activities.map((a:any)=><div key={a.id} className="flex items-center justify-between text-sm p-2 rounded hover:bg-accent"><span>{a.title} <span className="text-muted-foreground">({a.type})</span></span><span className="text-xs text-muted-foreground">{a.due_date || ''}</span></div>)}
              {data.recent_activities.length===0 && <div className="text-sm text-muted-foreground">Aucune activité</div>}
            </div>
          </CardContent>
        </Card>
        <Card className="bg-gradient-to-br from-sky-500 to-blue-600 text-white">
          <CardContent className="pt-6">
            <h3 className="font-bold">Besoin d'aide ?</h3>
            <p className="text-sm text-blue-100 mt-1">Configurez Ollama en local (gratuit) ou CodeCraftAPI pour activer l'assistant IA : résumés clients, brouillons d'emails et suggestions de relances.</p>
            <div className="flex gap-2 mt-4">
              <Link to="/ia" className="bg-white text-sky-700 px-4 py-1.5 rounded-lg text-sm font-medium">Configurer l'IA</Link>
              <a href={API_DOCS_URL} target="_blank" rel="noreferrer" className="bg-white/20 px-4 py-1.5 rounded-lg text-sm">API Docs</a>
            </div>
          </CardContent>
        </Card>
      </div>

      <div className="text-xs text-muted-foreground border-t pt-4">
        <div className="flex flex-wrap gap-4">
          <span>Durée moyenne du cycle: <b>{s.avg_cycle_days} jours</b></span>
          <span>Montant moyen: <b>{formatCurrency(s.avg_deal_amount)}</b></span>
          <span>Pipeline pondéré = somme(montant × probabilité%) hors Gagné/Perdu</span>
        </div>
      </div>
    </div>
  )
}
