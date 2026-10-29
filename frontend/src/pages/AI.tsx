import { useEffect, useState } from 'react'
import { api } from '../api/client'
import { Card, CardHeader, CardTitle, CardContent } from '../components/ui/card'
import { Button } from '../components/ui/button'
import { Input, Textarea } from '../components/ui/input'
import { Bot, Settings, CheckCircle2, XCircle, RefreshCw, Sparkles, Lightbulb, Target } from 'lucide-react'
import { toast } from 'sonner'

export function AIPage() {
  const [providers, setProviders] = useState<any[]>([])
  const [health, setHealth] = useState<any>(null)
  const [showOllama, setShowOllama] = useState(false)
  const [showCodecraft, setShowCodecraft] = useState(false)
  const [ollamaForm, setOllamaForm] = useState({ name:'Ollama Local', ollama_url:'http://host.docker.internal:11434', ollama_model:'llama3.2', is_active:true })
  const [codecraftForm, setCodecraftForm] = useState({ name:'CodeCraftAPI', api_base_url:'https://www.codecraftapi.com/v1', api_key:'', model_id:'gpt-4o-mini', is_active:true })
  const [prompt, setPrompt] = useState('Rédige un email de relance pour un devis envoyé il y a 5 jours sans réponse. Ton professionnel et bienveillant.')
  const [response, setResponse] = useState('')
  const [genLoading, setGenLoading] = useState(false)
  const [testing, setTesting] = useState<number|null>(null)

  const load = () => { api.get('/ai/providers').then(r=>setProviders(r.data)); api.get('/ai/health').then(r=>setHealth(r.data)) }
  useEffect(()=>{ load() }, [])

  const createOllama = async (e: React.FormEvent) => {
    e.preventDefault()
    try { await api.post('/ai/providers', { provider:'ollama', ...ollamaForm, is_default: providers.length===0 }); toast.success('Fournisseur Ollama créé'); setShowOllama(false); load() } catch(e:any){ toast.error(e.response?.data?.detail||'Erreur') }
  }
  const createCodecraft = async (e: React.FormEvent) => {
    e.preventDefault()
    try { await api.post('/ai/providers', { provider:'codecraftapi', ...codecraftForm, is_default: false }); setCodecraftForm(form => ({ ...form, api_key: '' })); toast.success('Fournisseur CodeCraftAPI créé'); setShowCodecraft(false); load() } catch(e:any){ toast.error(e.response?.data?.detail||'Erreur') }
  }
  const test = async (id:number) => {
    setTesting(id)
    try { const r=await api.post('/ai/providers/test', { provider_id: id }); toast[r.data.success ? 'success' : 'error'](r.data.message); load() } catch(e:any){ toast.error(e.response?.data?.detail||'Erreur') } finally { setTesting(null)}
  }
  const refreshModels = async (id:number) => {
    try { const r=await api.get(`/ai/providers/${id}/models`); toast.success(`Modèles: ${r.data.models.slice(0,3).join(', ')}`) } catch(e:any){ toast.error(e.response?.data?.detail||'Erreur') }
  }
  const generate = async () => {
    setGenLoading(true); setResponse('')
    try { const r=await api.post('/ai/generate', { prompt, feature:'email_draft' }); setResponse(r.data.content) } catch(e:any){ toast.error(e.response?.data?.detail||'Erreur'); setResponse('Erreur: vérifiez que Ollama est en cours (docker.host.internal) ou que la clé CodeCraftAPI est valide. L\'IA est facultative.') } finally { setGenLoading(false)}
  }

  return (
    <div className="p-4 lg:p-8 max-w-[1600px] mx-auto space-y-6">
      <div><h1 className="text-2xl font-bold flex items-center gap-2"><Bot className="w-6 h-6 text-violet-600"/>Intelligence Artificielle</h1><p className="text-sm text-muted-foreground">Module facultatif, isolé du cœur métier. Le CRM fonctionne entièrement sans IA.</p></div>

      {health && (
        <Card className={health.active_providers ? 'border-green-200 bg-green-50 dark:bg-green-950/20' : 'border-amber-200 bg-amber-50 dark:bg-amber-950/20'}>
          <CardContent className="pt-4 flex items-center gap-3">
            {health.active_providers ? <CheckCircle2 className="w-5 h-5 text-green-600"/> : <XCircle className="w-5 h-5 text-amber-600"/>}
            <div className="text-sm"><div className="font-medium">{health.active_providers ? `${health.active_providers} fournisseur(s) actif(s)` : 'Aucun fournisseur IA actif — Le CRM fonctionne sans IA'}</div><div className="text-muted-foreground">{health.message} • Configuration par défaut: modèle local Ollama (gratuit, open-weight)</div></div>
          </CardContent>
        </Card>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between"><CardTitle className="text-sm flex items-center gap-2"><Settings className="w-4 h-4"/>Fournisseurs configurés</CardTitle><span className="text-xs text-muted-foreground">{providers.length} fournisseur(s)</span></CardHeader>
          <CardContent className="space-y-3">
            {providers.map((p:any)=>(
              <div key={p.id} className="p-3 border rounded-lg">
                <div className="flex items-center justify-between">
                  <div>
                    <div className="font-medium text-sm">{p.name} <span className="text-xs px-1.5 py-0.5 rounded bg-slate-100">{p.provider}</span> {p.is_default && <span className="text-xs bg-sky-100 text-sky-700 px-1.5 py-0.5 rounded">Défaut</span>}</div>
                    <div className="text-xs text-muted-foreground">{p.provider==='ollama' ? `${p.ollama_url} • ${p.ollama_model}` : `${p.api_base_url} • ${p.model_id} • Clé: ${p.api_key_masked || 'non configurée'}`}</div>
                    {p.api_key_needs_reset && <div role="alert" className="text-xs text-amber-700">Clé ancienne ou illisible : un administrateur doit supprimer et recréer ce fournisseur avec une nouvelle clé.</div>}
                    <div className="text-xs">{p.is_active ? '✅ Actif' : '⏸️ Inactif'} {p.last_test_status && `• Test: ${p.last_test_status}`} {p.last_test_message && `• ${p.last_test_message.slice(0,60)}`}</div>
                  </div>
                  <div className="flex flex-col gap-1"><Button size="sm" variant="outline" onClick={()=>test(p.id)} disabled={testing===p.id}>{testing===p.id ? 'Test...' : 'Tester'}</Button><Button size="sm" variant="ghost" onClick={()=>refreshModels(p.id)}><RefreshCw className="w-3 h-3 mr-1"/>Modèles</Button><Button size="sm" variant="ghost" onClick={async()=>{ await api.delete(`/ai/providers/${p.id}`); load()}}>Suppr.</Button></div>
                </div>
              </div>
            ))}
            {providers.length===0 && <div className="text-sm text-muted-foreground py-4">Aucun fournisseur — Ajoutez Ollama (local, gratuit) ou CodeCraftAPI ci-dessous.</div>}
            <div className="flex gap-2">
              <Button onClick={()=>setShowOllama(true)} className="flex-1">+ Ollama Local</Button>
              <Button onClick={()=>setShowCodecraft(true)} variant="outline" className="flex-1">+ CodeCraftAPI</Button>
            </div>
          </CardContent>
        </Card>

        <Card className="bg-gradient-to-br from-violet-50 to-purple-50 dark:from-violet-950/20">
          <CardHeader><CardTitle className="text-sm flex items-center gap-2"><Sparkles className="w-4 h-4 text-violet-600"/>Tester l'assistant (facultatif)</CardTitle></CardHeader>
          <CardContent className="space-y-3">
            <Textarea value={prompt} onChange={e=>setPrompt(e.target.value)} rows={4} placeholder="Votre prompt..." />
            <Button onClick={generate} disabled={genLoading} className="w-full bg-violet-600 hover:bg-violet-700">{genLoading ? 'Génération...' : 'Générer avec IA'}</Button>
            {response && <div className="p-3 bg-white dark:bg-slate-900 border rounded-lg text-sm whitespace-pre-wrap max-h-64 overflow-auto">{response}<div className="text-xs text-muted-foreground mt-2">⚠️ Vérifiez les suggestions avant envoi — L'IA ne modifie jamais de données sans validation</div></div>}
            <div className="text-xs text-muted-foreground">L'IA distingue données vérifiées / estimations / suggestions. Aucune action externe sans autorisation.</div>
          </CardContent>
        </Card>
      </div>

      {showOllama && (
        <Card><CardHeader><CardTitle className="text-sm">Configurer Ollama (local, gratuit)</CardTitle><p className="text-xs text-muted-foreground">Modèles open-weight à licence commerciale vérifiée. Ne télécharge pas automatiquement — Administrateur choisit et confirme.</p></CardHeader><CardContent>
          <form onSubmit={createOllama} className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <div><label className="text-xs">Nom</label><Input value={ollamaForm.name} onChange={e=>setOllamaForm({...ollamaForm, name:e.target.value})} required /></div>
            <div><label className="text-xs">URL Ollama * (depuis Docker: host.docker.internal:11434)</label><Input value={ollamaForm.ollama_url} onChange={e=>setOllamaForm({...ollamaForm, ollama_url:e.target.value})} required placeholder="http://host.docker.internal:11434" /></div>
            <div><label className="text-xs">Modèle installé</label><Input value={ollamaForm.ollama_model} onChange={e=>setOllamaForm({...ollamaForm, ollama_model:e.target.value})} placeholder="llama3.2, mistral..." /></div>
            <div className="flex items-center gap-2"><input type="checkbox" checked={ollamaForm.is_active} onChange={e=>setOllamaForm({...ollamaForm, is_active:e.target.checked})} /><label className="text-xs">Activé</label></div>
            <div className="md:col-span-2 text-xs text-muted-foreground">En Docker, localhost du CRM ≠ localhost de la machine hôte. Utilisez <code>http://host.docker.internal:11434</code> pour joindre Ollama installé sur l'hôte. Voir guide installation Ollama ci-dessous.</div>
            <div className="flex gap-2 md:col-span-2"><Button type="submit">Enregistrer</Button><Button type="button" variant="outline" onClick={()=>setShowOllama(false)}>Annuler</Button></div>
          </form>
        </CardContent></Card>
      )}
      {showCodecraft && (
        <Card><CardHeader><CardTitle className="text-sm">Configurer CodeCraftAPI (compatible OpenAI)</CardTitle></CardHeader><CardContent>
          <form onSubmit={createCodecraft} className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <div><label className="text-xs">Nom</label><Input value={codecraftForm.name} onChange={e=>setCodecraftForm({...codecraftForm, name:e.target.value})} required /></div>
            <div><label className="text-xs">URL de base</label><Input value={codecraftForm.api_base_url} onChange={e=>setCodecraftForm({...codecraftForm, api_base_url:e.target.value})} placeholder="https://www.codecraftapi.com/v1" /></div>
            <div><label className="text-xs">Clé API secrète *</label><Input type="password" value={codecraftForm.api_key} onChange={e=>setCodecraftForm({...codecraftForm, api_key:e.target.value})} required placeholder="sk-..." /></div>
            <div><label className="text-xs">Modèle</label><Input value={codecraftForm.model_id} onChange={e=>setCodecraftForm({...codecraftForm, model_id:e.target.value})} placeholder="gpt-4o-mini, claude-3..." /></div>
            <div className="flex items-center gap-2"><input type="checkbox" checked={codecraftForm.is_active} onChange={e=>setCodecraftForm({...codecraftForm, is_active:e.target.checked})} /><label className="text-xs">Activé</label></div>
            <div className="md:col-span-2 text-xs text-muted-foreground">Découverte via GET /models et génération via POST /chat/completions (format OpenAI). La clé n'est jamais exposée côté frontend après enregistrement (affichage masqué).</div>
            <div className="flex gap-2 md:col-span-2"><Button type="submit">Enregistrer</Button><Button type="button" variant="outline" onClick={()=>{ setCodecraftForm(form => ({ ...form, api_key: '' })); setShowCodecraft(false) }}>Annuler</Button></div>
          </form>
        </CardContent></Card>
      )}

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <Card><CardHeader><CardTitle className="text-sm flex items-center gap-2"><Lightbulb className="w-4 h-4"/>Fonctionnalités IA</CardTitle></CardHeader><CardContent className="text-xs space-y-1 text-muted-foreground">
          <div>• Résumé fiche client & historique</div><div>• Rédaction relances & propositions</div><div>• Comptes rendus depuis notes</div><div>• Suggestions prochaine action</div><div>• Analyse gagné/perdu descriptive</div><div>• Recherche langage naturel (autorisée)</div><div>• Extraction structurée depuis texte</div><div>• Segmentation & priorisation prospects</div>
        </CardContent></Card>
        <Card><CardHeader><CardTitle className="text-sm flex items-center gap-2"><Target className="w-4 h-4"/>Contraintes</CardTitle></CardHeader><CardContent className="text-xs space-y-1 text-muted-foreground">
          <div>• Gratuit par défaut (Ollama local)</div><div>• Pas de fournisseur payant obligatoire</div><div>• CRM opérationnel sans IA</div><div>• Pas d'invention de données</div><div>• Pas de modification sensible sans validation</div><div>• Pas d'envoi externe sans canal configuré</div><div>• Données minimales transmises</div><div>• Info utilisateur si envoi externe</div>
        </CardContent></Card>
        <Card><CardHeader><CardTitle className="text-sm">Limites matérielles</CardTitle></CardHeader><CardContent className="text-xs space-y-1 text-muted-foreground">
          <div>Ollama local: 8 Go RAM recommandé pour llama3.2 (3B), 16 Go pour 7B.</div><div>Temps réponse: 2-10s selon modèle & machine.</div><div>Licences: vérifiez chaque modèle (ex: Llama 3.2, Mistral, Qwen autorisent usage commercial sous conditions).</div><div>CodeCraftAPI: consultez tarification & quotas directement sur codecraftapi.com (non supposé gratuit/illimité).</div>
        </CardContent></Card>
      </div>

      <Card><CardContent className="pt-4 text-xs text-muted-foreground">Architecture: chaque fournisseur a son adaptateur (OllamaProvider, OpenAICompatProvider) + AIServiceManager pour sélection par fonctionnalité. Ajout futur d'autres fournisseurs compatibles OpenAI sans réécrire le CRM.</CardContent></Card>
    </div>
  )
}
