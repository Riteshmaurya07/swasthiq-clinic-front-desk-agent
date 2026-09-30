import { useLocation,Link } from "react-router-dom"
import { MessageSquareText, Stethoscope } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import {
  Sidebar,
  SidebarContent,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarSeparator,
} from "@/components/ui/sidebar"

const NAV_ITEMS = [
  { title: "Handoff Queue", url: "/handoffs", icon: MessageSquareText, match: "/handoffs" },
]

/**
 * Shared sidebar persisting across both screens (mockup: narrow left rail).
 * The conversation detail route keeps the queue item active.
 */
export function AppSidebar() {
  const location = useLocation()

  return (
    <Sidebar collapsible="offcanvas">
      <SidebarHeader className="p-4">
        <div className="flex items-center gap-2 px-2">
          <div className="flex size-8 shrink-0 items-center justify-center rounded-md bg-primary text-primary-foreground">
            <Stethoscope className="size-4" />
          </div>
          <div className="flex min-w-0 flex-col">
            <span className="truncate text-sm font-semibold">Swasthiq Desk</span>
            <span className="truncate text-xs text-muted-foreground">Sunrise Clinic, Dehradun</span>
          </div>
        </div>
      </SidebarHeader>
      <SidebarSeparator />
      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupLabel>Operations</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              {NAV_ITEMS.map((item) => (
                <SidebarMenuItem key={item.url}>
                  <SidebarMenuButton
                    asChild
                    isActive={location.pathname.startsWith(item.match)}
                    tooltip={item.title}
                  >
                    <Link to={item.url}>
                      <item.icon />
                      <span>{item.title}</span>
                    </Link>
                  </SidebarMenuButton>
                </SidebarMenuItem>
              ))}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>
      <SidebarSeparator />
      <div className="p-4">
        <Badge variant="outline" className="text-[10px] font-medium tracking-wide text-muted-foreground">
          Deterministic agent · No LLM
        </Badge>
      </div>
    </Sidebar>
  )
}
