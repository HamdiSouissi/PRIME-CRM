import { NavLink, useNavigate } from 'react-router-dom'
import { LayoutDashboard, Users, Kanban, Calendar, FileText, Package, Settings, LogOut, Sun, Moon, Menu, X, ChevronLeft, Bot, BarChart3, Shield } from 'lucide-react'
import { useState, useEffect } from 'react'
import { clearAuth } from '../../api/client'

const links = [
  { to: '/', icon: LayoutDashboard, label: 'Tableau de bord' },
  { to: '/clients', icon: Users, label: 'Clients & Prospects' },
  { to: '/pipeline', icon: Kanban, label: 'Pipeline' },
  { to: '/activites', icon: Calendar, label: 'Agenda & Tâches' },
  { to: '/devis', icon: FileText, label: 'Devis' },
  { to: '/produits', icon: Package, label: 'Produits' },
  { to: '/analytics', icon: BarChart3, label: 'Analytics' },
  { to: '/ia', icon: Bot, label: 'Assistant IA' },
  { to: '/admin', icon: Shield, label: 'Administration' },
  { to: '/parametres', icon: Settings, label: 'Paramètres' },
]

export function Sidebar() {
  const [collapsed, setCollapsed] = useState(false)
  const [mobileOpen, setMobileOpen] = useState(false)
  const [dark, setDark] = useState(false)
  const navigate = useNavigate()
  const user = JSON.parse(localStorage.getItem('prime_user') || 'null')

  useEffect(() => {
    if (dark) document.documentElement.classList.add('dark')
    else document.documentElement.classList.remove('dark')
  }, [dark])

  const SidebarContent = () => (
    <div className={`flex flex-col h-full bg-white dark:bg-slate-900 border-r dark:border-slate-800 transition-all ${collapsed ? 'w-16' : 'w-64'}`}>
      <div className="flex items-center justify-between p-4 border-b dark:border-slate-800">
        {!collapsed && (
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-sky-500 to-blue-600 flex items-center justify-center text-white font-bold text-sm">PV</div>
            <div>
              <div className="font-bold text-sm">Prime CRM</div>
              <div className="text-xs text-muted-foreground">Prime Vision</div>
            </div>
          </div>
        )}
        {collapsed && <div className="w-8 h-8 rounded-lg bg-sky-500 flex items-center justify-center text-white font-bold text-xs mx-auto">PV</div>}
        <button onClick={() => setCollapsed(!collapsed)} className="p-1 hover:bg-accent rounded-md hidden lg:block"><ChevronLeft className={`w-4 h-4 transition-transform ${collapsed ? 'rotate-180' : ''}`} /></button>
        <button onClick={() => setMobileOpen(false)} className="p-1 hover:bg-accent rounded-md lg:hidden"><X className="w-5 h-5" /></button>
      </div>

      <nav className="flex-1 p-2 space-y-1 overflow-y-auto scrollbar-thin">
        {links.map(l => (
          <NavLink key={l.to} to={l.to} onClick={() => setMobileOpen(false)} className={({isActive}) => `flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors ${isActive ? 'bg-sky-50 dark:bg-sky-950 text-sky-700 dark:text-sky-300' : 'text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800'} ${collapsed ? 'justify-center' : ''}`}>
            <l.icon className="w-5 h-5 flex-shrink-0" />
            {!collapsed && <span className="truncate">{l.label}</span>}
          </NavLink>
        ))}
      </nav>

      <div className="p-3 border-t dark:border-slate-800 space-y-2">
        <div className={`flex items-center gap-3 ${collapsed ? 'justify-center' : ''}`}>
          <div className="w-8 h-8 rounded-full bg-gradient-to-br from-sky-500 to-blue-600 flex items-center justify-center text-white text-xs font-bold">{user ? `${user.first_name?.[0]}${user.last_name?.[0]}` : 'U'}</div>
          {!collapsed && <div className="flex-1 min-w-0"><div className="text-sm font-medium truncate">{user?.first_name} {user?.last_name}</div><div className="text-xs text-muted-foreground truncate">{user?.company_name}</div></div>}
        </div>
        <div className={`flex gap-1 ${collapsed ? 'flex-col' : ''}`}>
          <button onClick={() => setDark(!dark)} className="flex-1 flex items-center justify-center gap-2 px-2 py-1.5 text-xs rounded-md hover:bg-accent"><Sun className="w-3.5 h-3.5 dark:hidden" /><Moon className="w-3.5 h-3.5 hidden dark:block" />{!collapsed && (dark ? 'Clair' : 'Sombre')}</button>
          <button onClick={() => { clearAuth(); navigate('/login') }} className="flex items-center justify-center gap-2 px-2 py-1.5 text-xs rounded-md hover:bg-red-50 text-red-600"><LogOut className="w-3.5 h-3.5" />{!collapsed && 'Déconnexion'}</button>
        </div>
      </div>
    </div>
  )

  return (
    <>
      {/* Mobile top bar */}
      <div className="lg:hidden fixed top-0 left-0 right-0 z-30 bg-white dark:bg-slate-900 border-b dark:border-slate-800 flex items-center justify-between px-4 py-3">
        <div className="flex items-center gap-2"><div className="w-7 h-7 rounded-lg bg-sky-500 flex items-center justify-center text-white font-bold text-xs">PV</div><span className="font-bold">Prime CRM</span></div>
        <button onClick={() => setMobileOpen(true)} className="p-2 hover:bg-accent rounded-md"><Menu className="w-5 h-5" /></button>
      </div>

      {/* Desktop sidebar */}
      <div className="hidden lg:block sticky top-0 h-screen shrink-0">
        <SidebarContent />
      </div>

      {/* Mobile overlay */}
      {mobileOpen && (
        <div className="lg:hidden fixed inset-0 z-40 flex">
          <div className="flex-1 bg-black/50" onClick={() => setMobileOpen(false)} />
          <div className="w-64 bg-white dark:bg-slate-900"><SidebarContent /></div>
        </div>
      )}
    </>
  )
}
