import { Sidebar } from './Sidebar'
import { Outlet } from 'react-router-dom'
import { Toaster } from 'sonner'

export function Layout() {
  return (
    <div className="min-h-screen bg-slate-50 dark:bg-slate-950 flex">
      <Sidebar />
      <main className="flex-1 min-w-0">
        <div className="lg:pt-0 pt-14">
          <Outlet />
        </div>
      </main>
      <Toaster position="top-right" richColors />
    </div>
  )
}
