import { Navigate, Route, Routes } from "react-router-dom"

import { AppSidebar } from "@/components/layout/AppSidebar"
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar"
import { ConversationDetailPage } from "@/pages/ConversationDetail"
import { HandoffQueuePage } from "@/pages/HandoffQueue"

export default function App() {
  return (
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
  )
}
