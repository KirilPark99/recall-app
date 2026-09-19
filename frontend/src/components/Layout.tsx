import { NavLink, useLocation } from "react-router-dom";
import {
  BarChart3, FolderOpen, Home, Layers, LogOut, Settings, Shield, Sparkles, Repeat,
} from "lucide-react";
import { useApp } from "../state/AppContext";

const NAV = [
  { to: "/", key: "nav_home", icon: Home },
  { to: "/sets", key: "nav_sets", icon: Layers },
  { to: "/folders", key: "nav_folders", icon: FolderOpen },
  { to: "/review", key: "nav_review", icon: Repeat },
  { to: "/stats", key: "nav_stats", icon: BarChart3 },
  { to: "/discover", key: "nav_discover", icon: Sparkles },
  { to: "/settings", key: "nav_settings", icon: Settings },
] as const;

export function Layout({ children }: { children: React.ReactNode }) {
  const { user, t, logout } = useApp();
  const location = useLocation();
  const isStudy = location.pathname.startsWith("/study/");

  if (isStudy) {
    return <div className="min-h-screen">{children}</div>;
  }

  const desktopNav = NAV.filter((n) => n.to !== "/settings" || true);

  return (
    <div className="min-h-screen">
      {/* Mobile top header */}
      <header className="sticky top-0 z-30 flex items-center justify-between border-b px-4 py-3 bg-[var(--surface)]/95 backdrop-blur-sm md:hidden border-[var(--border)]">
        <NavLink to="/" className="flex items-center gap-2.5">
          <div
            className="flex h-8 w-8 items-center justify-center rounded-lg shadow-sm"
            style={{
              background: "linear-gradient(135deg, var(--accent) 0%, #6366f1 100%)",
              color: "#ffffff",
            }}
          >
            <Layers size={18} aria-hidden />
          </div>
          <span className="text-lg font-extrabold tracking-tight">Recall</span>
        </NavLink>
        <div className="flex items-center gap-2">
          <NavLink
            to="/settings"
            className="flex h-8 w-8 items-center justify-center rounded-full text-xs font-bold border border-[var(--border)]"
            style={{ background: "var(--surface-2)", color: "var(--accent)" }}
            title={user?.username}
          >
            {user?.username?.[0]?.toUpperCase() ?? "U"}
          </NavLink>
        </div>
      </header>

      <div className="mx-auto flex max-w-7xl">
        {/* Desktop sidebar */}
        <aside
          className="sticky top-0 hidden h-screen w-64 shrink-0 flex-col border-r px-4 py-6 md:flex"
          aria-label="Основная навигация"
          style={{ background: "var(--surface)" }}
        >
          <div className="mb-6 flex items-center gap-3 px-2">
            <div
              className="flex h-10 w-10 items-center justify-center rounded-xl shadow-sm"
              style={{
                background: "linear-gradient(135deg, var(--accent) 0%, #6366f1 100%)",
                color: "#ffffff",
              }}
            >
              <Layers size={22} aria-hidden />
            </div>
            <span className="text-xl font-extrabold tracking-tight">Recall</span>
          </div>

          <nav className="flex flex-1 flex-col gap-1.5 overflow-y-auto">
            {desktopNav.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.to === "/"}
                className={({ isActive }) =>
                  `flex items-center gap-3.5 rounded-xl px-3.5 py-2.5 text-[0.95rem] font-medium transition-all ${
                    isActive
                      ? "shadow-sm font-semibold"
                      : "hover:bg-[var(--surface-2)] text-[var(--text-muted)] hover:text-[var(--text)]"
                  }`
                }
                style={({ isActive }) =>
                  isActive
                    ? { background: "var(--accent-soft)", color: "var(--accent)" }
                    : undefined
                }
              >
                <item.icon size={20} aria-hidden />
                {t(item.key)}
              </NavLink>
            ))}

            {user?.role === "admin" && (
              <NavLink
                to="/admin"
                className={({ isActive }) =>
                  `flex items-center gap-3.5 rounded-xl px-3.5 py-2.5 text-[0.95rem] font-medium transition-all ${
                    isActive
                      ? "shadow-sm font-semibold"
                      : "hover:bg-[var(--surface-2)] text-[var(--text-muted)] hover:text-[var(--text)]"
                  }`
                }
                style={({ isActive }) =>
                  isActive
                    ? { background: "var(--accent-soft)", color: "var(--accent)" }
                    : undefined
                }
              >
                <Shield size={20} aria-hidden />
                {t("nav_admin")}
              </NavLink>
            )}
          </nav>

          <div className="border-t pt-4">
            <div className="mb-3 flex items-center gap-3 px-2">
              <div
                className="flex h-9 w-9 items-center justify-center rounded-full text-sm font-bold"
                style={{ background: "var(--surface-2)", color: "var(--accent)" }}
              >
                {user?.username?.[0]?.toUpperCase() ?? "U"}
              </div>
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-semibold">{user?.username}</p>
                <p className="text-xs text-[var(--text-muted)] capitalize">{user?.role || "user"}</p>
              </div>
            </div>
            <button className="btn btn-ghost w-full justify-start text-sm" onClick={() => void logout()}>
              <LogOut size={18} aria-hidden />
              {t("logout")}
            </button>
          </div>
        </aside>

        {/* Main Content Area */}
        <main className="min-w-0 flex-1 px-4 pb-28 pt-4 md:px-10 md:pb-12 md:pt-6">
          {children}
        </main>
      </div>

      {/* Mobile bottom nav with safe-area padding */}
      <nav
        className="fixed inset-x-0 bottom-0 z-40 flex border-t bg-[var(--surface)]/95 backdrop-blur-md shadow-lg md:hidden"
        style={{
          borderTopColor: "var(--border)",
          paddingBottom: "max(0.5rem, env(safe-area-inset-bottom))",
        }}
        aria-label="Навигация"
      >
        {NAV.slice(0, 5).map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.to === "/"}
            className={({ isActive }) =>
              `flex flex-1 flex-col items-center justify-center gap-0.5 py-2 px-0.5 text-[11px] font-medium transition-colors min-w-0 ${
                isActive ? "font-bold" : "text-[var(--text-muted)]"
              }`
            }
            style={({ isActive }) => (isActive ? { color: "var(--accent)" } : undefined)}
          >
            <item.icon size={20} aria-hidden />
            <span className="truncate max-w-full">{t(item.key)}</span>
          </NavLink>
        ))}
        <NavLink
          to="/settings"
          className={({ isActive }) =>
            `flex flex-1 flex-col items-center justify-center gap-0.5 py-2 px-0.5 text-[11px] font-medium transition-colors min-w-0 ${
              isActive ? "font-bold" : "text-[var(--text-muted)]"
            }`
          }
          style={({ isActive }) => (isActive ? { color: "var(--accent)" } : undefined)}
        >
          <Settings size={20} aria-hidden />
          <span className="truncate max-w-full">{t("nav_settings")}</span>
        </NavLink>
      </nav>
    </div>
  );
}
