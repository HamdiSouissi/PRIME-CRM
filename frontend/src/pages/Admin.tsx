import { useEffect, useState } from 'react'
import { api } from '../api/client'
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card'
import { Button } from '../components/ui/button'

export function Admin() {
  const [stats, setStats] = useState<any>(null)
  const [logs, setLogs] = useState<any>(null)
  const [health, setHealth] = useState<any>(null)

  useEffect(()=>{
    api.get('/admin/stats').then(r=>setStats(r.data)).catch(()=>{})
    api.get('/admin/audit-logs?limit=20').then(r=>setLogs(r.data)).catch(()=>{})
    api.get('/admin/health').then(r=>setHealth(r.data)).catch(()=>{ api.get('/health').then(r=>setHealth(r.data))})
  }, [])

  return (
    <div className="p-4 lg:p-8 max-w-[1600px] mx-auto space-y-4">
      <h1 className="text-2xl font-bold">Administration</h1>
      <p className="text-sm text-muted-foreground">Supervision, santé, audit, sauvegardes — Accès admin uniquement (vérifié côté serveur)</p>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <Card><CardContent className="pt-6 text-center"><div className="text-2xl font-bold">{stats?.users ?? '-'}</div><div className="text-xs text-muted-foreground">Utilisateurs</div></CardContent></Card>
        <Card><CardContent className="pt-6 text-center"><div className="text-2xl font-bold">{stats?.clients ?? '-'}</div><div className="text-xs text-muted-foreground">Clients</div></CardContent></Card>
        <Card><CardContent className="pt-6 text-center"><div className="text-2xl font-bold">{stats?.opportunities ?? '-'}</div><div className="text-xs text-muted-foreground">Opportunités</div></CardContent></Card>
        <Card><CardContent className="pt-6 text-center"><div className="text-2xl font-bold">{health?.database ?? health?.status ?? '-'}</div><div className="text-xs text-muted-foreground">Santé BDD</div></CardContent></Card>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Card><CardHeader><CardTitle className="text-sm">Santé système</CardTitle></CardHeader><CardContent className="text-xs space-y-1"><div>API: {health?.status || 'ok'} • Version: {health?.version || '1.0.0'}</div><div>Base: {health?.database || 'ok'}</div><div>Heure: {health?.timestamp || new Date().toISOString()}</div><div className="mt-2 p-2 bg-slate-50 dark:bg-slate-900 rounded">Redis reste à intégrer avant le premier déploiement public. Les volumes locaux Docker ne constituent pas une sauvegarde.</div></CardContent></Card>
        <Card><CardHeader><CardTitle className="text-sm">Sauvegardes & Restauration</CardTitle></CardHeader><CardContent className="space-y-2 text-sm">
          <div className="flex gap-2"><a href={`${api.defaults.baseURL}/admin/backup`}><Button size="sm">Télécharger JSON</Button></a><Button size="sm" variant="outline" onClick={async()=>{ 
            const r=await api.get('/admin/backup'); 
            const blob=new Blob([JSON.stringify(r.data,null,2)],{type:'application/json'}); 
            const url=URL.createObjectURL(blob); 
            const a=document.createElement('a'); 
            a.href=url; 
            const dateStr = new Date().toISOString().slice(0,10);
            a.download='backup-'+dateStr+'.json'; 
            a.click();
          }}>Exporter</Button></div>
          <p className="text-xs text-muted-foreground">La procédure de sauvegarde et de restauration doit être validée sur une base de test avant la mise en ligne.</p>
        </CardContent></Card>
      </div>

      <Card><CardHeader><CardTitle className="text-sm">Journaux d'audit (actions importantes)</CardTitle></CardHeader><CardContent>
        <div className="overflow-x-auto"><table className="w-full text-xs"><thead><tr className="text-left text-muted-foreground"><th className="p-2">Date</th><th>Action</th><th>Entité</th><th>Utilisateur</th><th>Détails</th></tr></thead><tbody>{logs?.items?.map((l:any)=><tr key={l.id} className="border-t"><td className="p-2">{new Date(l.created_at).toLocaleString('fr-TN')}</td><td><span className="px-1.5 py-0.5 rounded bg-slate-100">{l.action}</span></td><td>{l.entity_type} #{l.entity_id}</td><td>{l.user_id}</td><td className="max-w-[200px] truncate">{l.details}</td></tr>)}</tbody></table></div>
        {logs?.items?.length===0 && <div className="text-xs text-muted-foreground py-4">Aucun log</div>}
        <div className="text-xs text-muted-foreground mt-2">Journalisation: create/update/delete/login/export/merge/stage_change • Conservation & suppression configurables • Accès non autorisé bloqué (tests d'isolation).</div>
      </CardContent></Card>

      <Card className="bg-amber-50 dark:bg-amber-950/20 border-amber-200"><CardContent className="pt-4 text-xs">Sécurité : accès privé et authentification par mot de passe. La limitation des tentatives, la protection des clés IA et l'intégration Redis restent à finaliser avant toute exposition publique. Voir docs/security.md.</CardContent></Card>
    </div>
  )
}
