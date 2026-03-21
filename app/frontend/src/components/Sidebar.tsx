"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import {
  LayoutDashboard,
  Music,
  Zap,
  Share2,
  BarChart3,
  Settings,
  Menu,
  X,
  LogOut,
  TrendingUp,
  ListOrdered,
  Palette,
  ShoppingBag,
  Bell,
  BellOff,
  BellRing,
  Youtube,
  CalendarClock,
  Film,
  Shield,
  Disc3,
  Link2,
  Layers,
} from "lucide-react";
import { useTheme } from "@/hooks/useTheme";
import { useAuth } from "@/hooks/useAuth";
import { useNotifications } from "@/hooks/useNotifications";

const MAIN_NAV = [
  { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { href: "/beats", label: "Beats", icon: Music },
  { href: "/automation", label: "Automation", icon: Zap },
  { href: "/render-studio", label: "Render Studio", icon: Film },
  { href: "/media-manager", label: "Media", icon: Shield },
  { href: "/trends", label: "Trends", icon: TrendingUp },
  { href: "/dj", label: "DJ", icon: Disc3 },
  { href: "/arranger", label: "Arranger", icon: Layers },
  { href: "/queue", label: "Queue", icon: ListOrdered },
  { href: "/brand", label: "Brand", icon: Palette },
  { href: "/stores", label: "Stores", icon: ShoppingBag },
  { href: "/organizer", label: "Organizer", icon: Link2 },
  { href: "/channel", label: "Channel", icon: Youtube },
  { href: "/scheduler", label: "Scheduler", icon: CalendarClock },
  { href: "/social", label: "Social", icon: Share2 },
  { href: "/analytics", label: "Analytics", icon: BarChart3 },
];

const BOTTOM_NAV = [
  { href: "/settings", label: "Settings", icon: Settings },
];

export default function Sidebar() {
  const pathname = usePathname();
  const { theme, setTheme, themes } = useTheme();
  const { user, logout } = useAuth();
  const { status: notifStatus, subscribed, loading: notifLoading, subscribe, unsubscribe } = useNotifications();
  const [open, setOpen] = useState(false);

  const renderNavItem = (item: (typeof MAIN_NAV)[number]) => {
    const { href, label, icon: Icon } = item;
    const active = pathname === href || pathname.startsWith(href + "/");

    return (
      <Link
        key={href}
        href={href}
        prefetch={false}
        onClick={() => setOpen(false)}
        className="flex items-center gap-3 px-3 h-10 rounded-xl text-[13px] font-medium transition-all duration-200 relative"
        style={
          active
            ? {
                background: "linear-gradient(135deg, var(--accent), color-mix(in srgb, var(--accent) 70%, #8b5cf6))",
                color: "#fff",
                boxShadow: "0 4px 16px var(--accent-muted)",
              }
            : { color: "var(--text-secondary)" }
        }
        onMouseEnter={(e) => {
          if (!active) {
            e.currentTarget.style.background = "var(--bg-hover)";
            e.currentTarget.style.color = "var(--text-primary)";
          }
        }}
        onMouseLeave={(e) => {
          if (!active) {
            e.currentTarget.style.background = "transparent";
            e.currentTarget.style.color = "var(--text-secondary)";
          }
        }}
      >
        <Icon size={17} strokeWidth={active ? 2.2 : 1.6} />
        {label}
      </Link>
    );
  };

  const nav = (
    <div className="flex flex-col h-full">
      {/* Logo + Notification Bell */}
      <div
        className="h-16 flex items-center px-5 justify-between"
        style={{ borderBottom: "1px solid var(--glass-border)" }}
      >
        <div className="flex items-center gap-3">
          <div
            className="w-10 h-10 rounded-xl flex items-center justify-center flex-shrink-0"
            style={{
              background: "linear-gradient(135deg, var(--accent), #8b5cf6)",
              boxShadow: "0 4px 16px var(--accent-muted)",
            }}
          >
            <Music size={18} className="text-white" strokeWidth={2.5} />
          </div>
          <div>
            <h1 className="text-xl font-black tracking-tight text-foreground leading-none">
              FY3<span style={{ color: "var(--accent)" }}>!</span>
            </h1>
            <p
              className="text-[9px] font-semibold tracking-[0.25em] uppercase leading-none mt-0.5"
              style={{ color: "var(--text-tertiary)" }}
            >
              Studio
            </p>
          </div>
        </div>
        {/* Notification bell */}
        {notifStatus !== "unsupported" && (
          <button
            onClick={async () => {
              if (subscribed) {
                await unsubscribe();
              } else {
                await subscribe();
              }
            }}
            disabled={notifLoading}
            title={
              notifStatus === "denied"
                ? "Notifications blocked — enable in browser settings"
                : subscribed
                  ? "Disable push notifications"
                  : "Enable push notifications"
            }
            className="p-2 rounded-lg transition-all duration-200 cursor-pointer relative"
            style={{
              color: subscribed ? "var(--accent)" : "var(--text-tertiary)",
              opacity: notifLoading ? 0.5 : 1,
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.background = "var(--bg-hover)";
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.background = "transparent";
            }}
          >
            {notifStatus === "denied" ? (
              <BellOff size={16} />
            ) : subscribed ? (
              <BellRing size={16} />
            ) : (
              <Bell size={16} />
            )}
            {subscribed && (
              <span
                className="absolute top-1.5 right-1.5 w-2 h-2 rounded-full"
                style={{ background: "var(--accent)", boxShadow: "0 0 6px var(--accent)" }}
              />
            )}
          </button>
        )}
      </div>

      {/* Main Nav — 5 items */}
      <nav className="flex-1 px-3 py-4 space-y-1 overflow-y-auto">
        {MAIN_NAV.map(renderNavItem)}
      </nav>

      {/* Settings — pinned above theme */}
      <div className="px-3 pb-1">
        <div
          className="mb-3"
          style={{ borderTop: "1px solid var(--glass-border)" }}
        />
        {BOTTOM_NAV.map(renderNavItem)}
      </div>

      {/* Theme Switcher */}
      <div
        className="px-5 py-3"
        style={{ borderTop: "1px solid var(--glass-border)" }}
      >
        <div className="flex items-center gap-2">
          {themes.map((t) => {
            const isActive = theme === t.id;
            return (
              <button
                key={t.id}
                onClick={() => setTheme(t.id)}
                title={t.label}
                aria-label={`Switch to ${t.label} theme`}
                className="rounded-full transition-all duration-200 cursor-pointer flex-shrink-0"
                style={{
                  width: isActive ? 18 : 12,
                  height: isActive ? 18 : 12,
                  background: t.color,
                  opacity: isActive ? 1 : 0.35,
                  border: isActive ? `2px solid ${t.color}` : "2px solid transparent",
                  boxShadow: isActive ? `0 0 10px ${t.color}60` : "none",
                }}
              />
            );
          })}
        </div>
      </div>

      {/* User info + Logout */}
      <div
        className="px-4 py-3 flex items-center gap-3"
        style={{ borderTop: "1px solid var(--glass-border)" }}
      >
        <div
          className="w-9 h-9 rounded-xl flex items-center justify-center flex-shrink-0"
          style={{
            background: "linear-gradient(135deg, var(--accent), #8b5cf6)",
            padding: "2px",
          }}
        >
          <div
            className="w-full h-full rounded-[10px] flex items-center justify-center"
            style={{ background: "var(--bg-card-solid)" }}
          >
            <span className="text-xs font-bold text-accent uppercase">
              {(user?.display_name || user?.username || "U").charAt(0)}
            </span>
          </div>
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-[12px] font-semibold truncate text-foreground leading-tight">
            {user?.display_name || user?.username || "User"}
          </p>
          <span
            className="text-[9px] font-semibold uppercase tracking-wider leading-tight inline-block mt-0.5 px-1.5 py-0.5 rounded"
            style={{ color: "var(--accent)", background: "var(--accent-muted)" }}
          >
            {user?.role || "producer"}
          </span>
        </div>
        <button
          onClick={logout}
          title="Sign out"
          className="p-2 rounded-lg transition-all duration-200 cursor-pointer"
          style={{ color: "var(--text-tertiary)" }}
          onMouseEnter={(e) => {
            e.currentTarget.style.background = "var(--bg-hover)";
            e.currentTarget.style.color = "var(--text-primary)";
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.background = "transparent";
            e.currentTarget.style.color = "var(--text-tertiary)";
          }}
        >
          <LogOut size={15} />
        </button>
      </div>
    </div>
  );

  return (
    <>
      {/* Mobile hamburger */}
      <button
        onClick={() => setOpen(!open)}
        aria-label={open ? "Close navigation menu" : "Open navigation menu"}
        className="fixed top-3 left-3 z-50 p-2.5 rounded-xl md:hidden transition-all duration-200"
        style={{
          background: "var(--bg-card)",
          backdropFilter: "blur(16px)",
          WebkitBackdropFilter: "blur(16px)",
          color: "var(--text-primary)",
          border: "1px solid var(--glass-border)",
          boxShadow: "0 4px 16px rgba(0,0,0,0.3)",
        }}
      >
        {open ? <X size={18} /> : <Menu size={18} />}
      </button>

      {/* Mobile overlay */}
      {open && (
        <div
          className="fixed inset-0 z-30 md:hidden"
          style={{ background: "rgba(0,0,0,0.6)", backdropFilter: "blur(4px)" }}
          onClick={() => setOpen(false)}
        />
      )}

      {/* Sidebar */}
      <aside
        className={`glass-sidebar fixed top-0 left-0 z-40 h-screen w-[240px] transition-transform duration-300 md:translate-x-0 ${
          open ? "translate-x-0" : "-translate-x-full"
        }`}
      >
        {nav}
      </aside>
    </>
  );
}
