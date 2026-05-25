import { useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { Outlet } from 'react-router-dom'

import { applyAccent } from '../../lib/accent'
import { apiFetch } from '../../lib/api'
import { Sidebar } from './Sidebar'
import { Topbar } from './Topbar'

export function AppLayout() {
  const [collapsed, setCollapsed] = useState(false)
  const { data: settings } = useQuery({
    queryKey: ['settings'],
    queryFn: () => apiFetch<{ organization: { accent_color: string | null } }>('/api/settings'),
    staleTime: 5 * 60 * 1000,
  })
  useEffect(() => {
    applyAccent(settings?.organization?.accent_color)
  }, [settings])

  return (
    <div className="flex h-screen overflow-hidden bg-bg text-body">
      <Sidebar collapsed={collapsed} badges={{ calls: 3 }} />
      <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
        <Topbar collapsed={collapsed} onToggleCollapse={() => setCollapsed((c) => !c)} />
        <main className="flex-1 overflow-y-auto">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
