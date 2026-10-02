import { Navigate, Route, Routes } from "react-router-dom"

import { DashboardSessionProvider } from "@/components/auth/DashboardSession"
import { AppSidebar } from "@/components/layout/AppSidebar"
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar"
import { ConversationDetailPage } from "@/pages/ConversationDetail"
import { HandoffQueuePage } from "@/pages/HandoffQueue"

/**
 * H-2: every dashboard route below the provider is session-protected. Until a
 * session exists the provider renders the sign-in screen, so no conversation or
 * handoff request is ever issued without one.
 */
export default function App() {
  return (
    <DashboardSessionProvider>
      <SidebarProvider>
        <AppSidebar />
        <SidebarInset>
          <Routes>
            <Route path="/" element={<Navigate to="/handoffs" replace />} />
            <Route path="/handoffs" element={<HandoffQueuePage />} />
            <Route path="/conversations/:conversationId" element={<ConversationDetailPage />} />
            <Route path="*" element={<Navigate to="/handoffs" replace />} />
          </Routes>
        </SidebarInset>
      </SidebarProvider>
    </DashboardSessionProvider>
  )
}
