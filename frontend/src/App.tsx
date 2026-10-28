import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { Layout } from './components/layout/Layout'
import { Login } from './pages/Login'
import { Dashboard } from './pages/Dashboard'
import { Clients } from './pages/Clients'
import { ClientDetail } from './pages/ClientDetail'
import { Pipeline } from './pages/Pipeline'
import { Activities } from './pages/Activities'
import { Quotes } from './pages/Quotes'
import { Products } from './pages/Products'
import { AIPage } from './pages/AI'
import { Settings } from './pages/Settings'
import { Admin } from './pages/Admin'

function RequireAuth({ children }: { children: React.ReactNode }) {
  const token = localStorage.getItem('prime_token')
  if (!token) return <Navigate to="/login" replace />
  return <>{children}</>
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route element={<RequireAuth><Layout /></RequireAuth>}>
          <Route path="/" element={<Dashboard />} />
          <Route path="/analytics" element={<Dashboard />} />
          <Route path="/clients" element={<Clients />} />
          <Route path="/clients/:id" element={<ClientDetail />} />
          <Route path="/pipeline" element={<Pipeline />} />
          <Route path="/activites" element={<Activities />} />
          <Route path="/devis" element={<Quotes />} />
          <Route path="/produits" element={<Products />} />
          <Route path="/ia" element={<AIPage />} />
          <Route path="/parametres" element={<Settings />} />
          <Route path="/admin" element={<Admin />} />
        </Route>
        <Route path="*" element={<div className="p-8">Page non trouvée — <a href="/" className="text-sky-600">Retour tableau de bord</a></div>} />
      </Routes>
    </BrowserRouter>
  )
}
