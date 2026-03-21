"use client";

import { useState, useMemo, useCallback } from "react";
import {
  Settings,
  Check,
  Youtube,
  Instagram,
  Music2,
  Wifi,
  WifiOff,
  RefreshCw,
  Plug,
  ChevronDown,
  User,
  Sparkles,
  Key,
  Eye,
  EyeOff,
  Loader2,
  Server,
  FolderOpen,
  Info,
  ExternalLink,
  UserPlus,
  Trash2,
  Users,
  Shield,
  Copy,
  Calendar,
  Clock,
  Plus,
  X as XIcon,
  ShoppingBag,
  Store,
  DollarSign,
} from "lucide-react";
import { useTheme, THEMES, type Theme } from "@/hooks/useTheme";
import { useSettings } from "@/hooks/useSettings";
import { useSchedule } from "@/hooks/useSchedule";
import { useStores } from "@/hooks/useStores";
import { useFetch, api } from "@/hooks/useApi";
import { useToast } from "@/components/ToastProvider";
import { useAuth } from "@/hooks/useAuth";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Switch } from "@/components/ui/switch";

/* ── Theme preview mini-colors ────────────────────────── */

const THEME_PREVIEWS: Record<
  Theme,
  { bg: string; card: string; text: string; accent: string; secondary: string }
> = {
  midnight: {
    bg: "#000000",
    card: "#1a1a1a",
    text: "#f5f5f7",
    accent: "#0a84ff",
    secondary: "#86868b",
  },
  studio: {
    bg: "#0d0b08",
    card: "#1e1a16",
    text: "#f5f5f7",
    accent: "#ff9f0a",
    secondary: "#86868b",
  },
  frost: {
    bg: "#f5f5f7",
    card: "#ffffff",
    text: "#1d1d1f",
    accent: "#0071e3",
    secondary: "#6e6e73",
  },
  neon: {
    bg: "#0a0010",
    card: "#1a0030",
    text: "#f5f5f7",
    accent: "#bf5af2",
    secondary: "#86868b",
  },
  ember: {
    bg: "#0d0506",
    card: "#1a0a0e",
    text: "#f5f5f7",
    accent: "#ff375f",
    secondary: "#86868b",
  },
  moss: {
    bg: "#040d06",
    card: "#0c1a0e",
    text: "#f5f5f7",
    accent: "#30d158",
    secondary: "#86868b",
  },
  ocean: {
    bg: "#020a14",
    card: "#081828",
    text: "#f5f5f7",
    accent: "#64d2ff",
    secondary: "#86868b",
  },
  sunset: {
    bg: "#0d0605",
    card: "#1a100c",
    text: "#f5f5f7",
    accent: "#ff6b6b",
    secondary: "#86868b",
  },
};

/* ── Integration card data ────────────────────────────── */

interface Integration {
  id: string;
  name: string;
  icon: typeof Youtube;
  connected: boolean;
  detail: string;
  actionLabel: string;
}

const BASE_INTEGRATIONS: Integration[] = [
  {
    id: "youtube",
    name: "YouTube",
    icon: Youtube,
    connected: true,
    detail: "BiggKutt8",
    actionLabel: "Reconnect",
  },
  {
    id: "instagram",
    name: "Instagram",
    icon: Instagram,
    connected: true,
    detail: "@fy3beats",
    actionLabel: "Reconnect",
  },
  {
    id: "tiktok",
    name: "TikTok",
    icon: Music2,
    connected: false,
    detail: "Not connected",
    actionLabel: "Connect",
  },
  {
    id: "suno",
    name: "Suno AI (Studio)",
    icon: Sparkles,
    connected: false,
    detail: "API key not set",
    actionLabel: "Configure",
  },
  {
    id: "replicate",
    name: "Replicate (AI Thumbnails)",
    icon: Sparkles,
    connected: false,
    detail: "API token not set",
    actionLabel: "Configure",
  },
  {
    id: "airbit",
    name: "Airbit",
    icon: ShoppingBag,
    connected: false,
    detail: "Not connected",
    actionLabel: "Connect",
  },
  {
    id: "beatstars",
    name: "BeatStars",
    icon: Store,
    connected: false,
    detail: "Not connected",
    actionLabel: "Connect",
  },
];

/* ── Main page ────────────────────────────────────────── */

interface ManagedUser {
  username: string;
  role: string;
  display_name?: string;
  created_at?: string;
}

export default function SettingsPage() {
  const { theme, setTheme, themes } = useTheme();
  const { settings, updateSetting } = useSettings();
  const {
    settings: scheduleSettings,
    updateSettings: updateScheduleSettings,
  } = useSchedule();
  const { toast } = useToast();
  const { isAdmin } = useAuth();

  // Schedule settings state
  const [schedNewTime, setSchedNewTime] = useState("12:00");
  const [schedEditingTimes, setSchedEditingTimes] = useState(false);
  const { data: integrationStatus } = useFetch<
    Record<string, { connected: boolean; detail: string }>
  >("/integrations/status");

  // ── User management state (admin only) ──
  const {
    data: usersData,
    mutate: refreshUsers,
  } = useFetch<{ users: ManagedUser[] }>(isAdmin ? "/auth/users" : null);

  const [newUsername, setNewUsername] = useState("");
  const [newDisplayName, setNewDisplayName] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [creatingUser, setCreatingUser] = useState(false);
  const [deletingUser, setDeletingUser] = useState<string | null>(null);
  const [showAddForm, setShowAddForm] = useState(false);
  const [generatedPassword, setGeneratedPassword] = useState("");

  const generatePassword = useCallback(() => {
    const chars = "abcdefghijkmnpqrstuvwxyz23456789";
    let pw = "";
    for (let i = 0; i < 10; i++) pw += chars[Math.floor(Math.random() * chars.length)];
    return pw;
  }, []);

  const handleCreateUser = async () => {
    const username = newUsername.trim().toLowerCase().replace(/[^a-z0-9_-]/g, "");
    if (!username || username.length < 2) {
      toast("Username must be at least 2 characters (letters, numbers, _ or -)", "error");
      return;
    }
    const password = newPassword || generatePassword();
    setCreatingUser(true);
    try {
      await api.post("/auth/users", {
        username,
        password,
        display_name: newDisplayName.trim() || username,
      });
      setGeneratedPassword(password);
      toast(`Producer "${username}" created`, "success");
      setNewUsername("");
      setNewDisplayName("");
      setNewPassword("");
      refreshUsers();
    } catch (err: any) {
      const msg = err?.message || "Failed to create user";
      toast(msg, "error");
    } finally {
      setCreatingUser(false);
    }
  };

  const handleDeleteUser = async (username: string) => {
    setDeletingUser(username);
    try {
      await api.del(`/auth/users/${username}`);
      toast(`Producer "${username}" deleted`, "success");
      refreshUsers();
    } catch (err: any) {
      toast(err?.message || "Failed to delete user", "error");
    } finally {
      setDeletingUser(null);
    }
  };

  const copyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text);
    toast("Copied to clipboard", "success");
  };

  const producers = usersData?.users?.filter((u) => u.role === "producer") || [];

  const integrations = useMemo(() => {
    if (!integrationStatus) return BASE_INTEGRATIONS;
    return BASE_INTEGRATIONS.map((intg) => {
      const live = integrationStatus[intg.id];
      if (!live) return intg;
      return {
        ...intg,
        connected: live.connected,
        detail: live.connected ? intg.detail : live.detail,
        actionLabel: live.connected ? "Reconnect" : "Connect",
      };
    });
  }, [integrationStatus]);
  const [privacyOpen, setPrivacyOpen] = useState(false);

  // Suno API key state
  const [sunoKeyInput, setSunoKeyInput] = useState("");
  const [sunoKeyVisible, setSunoKeyVisible] = useState(false);
  const [savingKey, setSavingKey] = useState(false);
  const [sunoKeyOpen, setSunoKeyOpen] = useState(false);

  // Replicate API key state
  const [replicateKeyInput, setReplicateKeyInput] = useState("");
  const [replicateKeyVisible, setReplicateKeyVisible] = useState(false);
  const [savingReplicateKey, setSavingReplicateKey] = useState(false);
  const [replicateKeyOpen, setReplicateKeyOpen] = useState(false);

  // Store credentials state (skip listings fetch — settings only needs pricing/credentials)
  const {
    pricing: storePricing,
    savePricing: saveStorePricing,
    saveCredentials: saveStoreCreds,
    disconnectStore,
  } = useStores({ skipListings: true });
  const [airbitOpen, setAirbitOpen] = useState(false);
  const [airbitEmail, setAirbitEmail] = useState("");
  const [airbitKey, setAirbitKey] = useState("");
  const [airbitUrl, setAirbitUrl] = useState("");
  const [airbitKeyVisible, setAirbitKeyVisible] = useState(false);
  const [savingAirbit, setSavingAirbit] = useState(false);

  const [beatstarsOpen, setBeatstarsOpen] = useState(false);
  const [beatstarsEmail, setBeatstarsEmail] = useState("");
  const [beatstarsKey, setBeatstarsKey] = useState("");
  const [beatstarsUrl, setBeatstarsUrl] = useState("");
  const [beatstarsKeyVisible, setBeatstarsKeyVisible] = useState(false);
  const [savingBeatstars, setSavingBeatstars] = useState(false);

  const [pricingOpen, setPricingOpen] = useState(false);
  const [basicPrice, setBasicPrice] = useState(storePricing.basic_license);
  const [premiumPrice, setPremiumPrice] = useState(storePricing.premium_license);
  const [exclusivePrice, setExclusivePrice] = useState(storePricing.exclusive_license);
  const [savingPricing, setSavingPricing] = useState(false);

  const handleSaveSunoKey = async () => {
    if (!sunoKeyInput || sunoKeyInput.length < 10) {
      toast("Please enter a valid API key", "error");
      return;
    }
    setSavingKey(true);
    try {
      await api.post("/studio/api-key", { key: sunoKeyInput });
      toast("Suno API key saved successfully", "success");
      setSunoKeyInput("");
      setSunoKeyOpen(false);
      // Reload the page to refresh integration status
      window.location.reload();
    } catch {
      toast("Failed to save API key", "error");
    } finally {
      setSavingKey(false);
    }
  };

  const handleSaveReplicateKey = async () => {
    if (!replicateKeyInput || replicateKeyInput.length < 10) {
      toast("Please enter a valid API token", "error");
      return;
    }
    setSavingReplicateKey(true);
    try {
      await api.post("/beats/ai-thumbnail/api-key", { key: replicateKeyInput });
      toast("Replicate API token saved successfully", "success");
      setReplicateKeyInput("");
      setReplicateKeyOpen(false);
      window.location.reload();
    } catch {
      toast("Failed to save API token", "error");
    } finally {
      setSavingReplicateKey(false);
    }
  };

  const handleSaveAirbit = async () => {
    if (!airbitKey || airbitKey.length < 5) {
      toast("Please enter a valid API key", "error");
      return;
    }
    setSavingAirbit(true);
    try {
      await saveStoreCreds("airbit", { email: airbitEmail, api_key: airbitKey, store_url: airbitUrl });
      toast("Airbit connected successfully", "success");
      setAirbitKey("");
      setAirbitOpen(false);
      window.location.reload();
    } catch {
      toast("Failed to save Airbit credentials", "error");
    } finally {
      setSavingAirbit(false);
    }
  };

  const handleSaveBeatstars = async () => {
    if (!beatstarsKey || beatstarsKey.length < 5) {
      toast("Please enter a valid API key / token", "error");
      return;
    }
    setSavingBeatstars(true);
    try {
      await saveStoreCreds("beatstars", { email: beatstarsEmail, api_key: beatstarsKey, store_url: beatstarsUrl });
      toast("BeatStars connected successfully", "success");
      setBeatstarsKey("");
      setBeatstarsOpen(false);
      window.location.reload();
    } catch {
      toast("Failed to save BeatStars credentials", "error");
    } finally {
      setSavingBeatstars(false);
    }
  };

  const handleSavePricing = async () => {
    setSavingPricing(true);
    try {
      await saveStorePricing({ basic_license: basicPrice, premium_license: premiumPrice, exclusive_license: exclusivePrice });
      toast("Default pricing saved", "success");
      setPricingOpen(false);
    } catch {
      toast("Failed to save pricing", "error");
    } finally {
      setSavingPricing(false);
    }
  };

  const handleDisconnectStore = async (platform: string) => {
    try {
      await disconnectStore(platform);
      toast(`${platform === "airbit" ? "Airbit" : "BeatStars"} disconnected`, "success");
      window.location.reload();
    } catch {
      toast("Failed to disconnect", "error");
    }
  };

  const privacy = settings.defaultPrivacy;
  const artistName = settings.artistName;
  const autoRender = settings.autoRender;
  const autoUpload = settings.autoUpload;

  const privacyOptions = [
    { value: "public", label: "Public" },
    { value: "unlisted", label: "Unlisted" },
    { value: "private", label: "Private" },
  ];

  return (
    <div className="animate-fade-in">
      {/* ── Header ─────────────────────────────────────── */}
      <div className="page-header">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <div>
            <h1 className="flex items-center gap-2">
              <Settings size={20} className="text-accent" />
              Settings
            </h1>
            <p className="text-sm text-text-secondary mt-1">Configuration & integrations</p>
          </div>
        </div>
      </div>

      {/* ── Theme Selector ─────────────────────────────── */}
      <section className="mb-10">
        <h2 className="text-lg font-semibold mb-4 text-foreground">
          Theme
        </h2>
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          {themes.map((t) => {
            const active = theme === t.id;
            const preview = THEME_PREVIEWS[t.id];
            return (
              <button
                key={t.id}
                onClick={() => setTheme(t.id)}
                className={`rounded-lg p-4 text-left transition-all duration-200 cursor-pointer relative overflow-hidden bg-card border-2 ${
                  active ? "" : "border-border hover:border-border-light"
                }`}
                style={active ? { borderColor: t.color } : undefined}
              >
                {/* Active check */}
                {active && (
                  <div
                    className="absolute top-3 right-3 w-6 h-6 rounded-full flex items-center justify-center"
                    style={{ background: t.color }}
                  >
                    <Check size={14} color="#fff" strokeWidth={2.5} />
                  </div>
                )}

                {/* Mini preview */}
                <div
                  className="rounded-lg mb-3 p-3 overflow-hidden"
                  style={{
                    background: preview.bg,
                    border: `1px solid ${t.id === "frost" ? "#d2d2d7" : "rgba(255,255,255,0.06)"}`,
                  }}
                >
                  {/* Faux sidebar + content */}
                  <div className="flex gap-2" style={{ height: 48 }}>
                    <div
                      className="rounded-md"
                      style={{
                        width: 36,
                        background: preview.card,
                        border: `1px solid ${t.id === "frost" ? "#e5e5ea" : "rgba(255,255,255,0.05)"}`,
                      }}
                    />
                    <div className="flex-1 flex flex-col gap-1.5">
                      <div
                        className="rounded-sm"
                        style={{ height: 6, width: "60%", background: preview.text, opacity: 0.7 }}
                      />
                      <div
                        className="rounded-sm"
                        style={{ height: 4, width: "80%", background: preview.secondary, opacity: 0.5 }}
                      />
                      <div className="flex gap-1 mt-auto">
                        <div
                          className="rounded-sm"
                          style={{ height: 10, width: 24, background: preview.accent, opacity: 0.8, borderRadius: 3 }}
                        />
                        <div
                          className="rounded-sm"
                          style={{ height: 10, width: 18, background: preview.card, borderRadius: 3 }}
                        />
                      </div>
                    </div>
                  </div>
                </div>

                {/* Label row */}
                <div className="flex items-center gap-2">
                  <div
                    className="w-4 h-4 rounded-full"
                    style={{
                      background: t.color,
                      boxShadow: active ? `0 0 8px ${t.color}60` : "none",
                    }}
                  />
                  <span className="text-sm font-medium text-foreground">
                    {t.label}
                  </span>
                </div>
              </button>
            );
          })}
        </div>
      </section>

      {/* ── Integrations ───────────────────────────────── */}
      <section className="mb-10">
        <h2 className="text-lg font-semibold mb-4 text-foreground">
          Integrations
        </h2>
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {integrations.map((intg) => {
            const Icon = intg.icon;
            return (
              <div
                key={intg.id}
                className="rounded-lg p-5 flex items-center gap-4 transition-all duration-200 bg-card border border-border hover:border-border-light"
              >
                {/* Icon */}
                <div
                  className={`w-11 h-11 rounded-lg flex items-center justify-center flex-shrink-0 ${
                    intg.connected ? "bg-accent-muted" : "bg-muted"
                  }`}
                >
                  <Icon
                    size={20}
                    strokeWidth={1.8}
                    className={intg.connected ? "text-accent" : "text-text-tertiary"}
                  />
                </div>

                {/* Info */}
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-0.5">
                    <span className="text-sm font-semibold text-foreground">
                      {intg.name}
                    </span>
                    <span
                      className={`w-2 h-2 rounded-full flex-shrink-0 ${
                        intg.connected ? "bg-success" : "bg-error"
                      }`}
                      style={{
                        boxShadow: intg.connected
                          ? "0 0 6px rgba(48,209,88,0.4)"
                          : "0 0 6px rgba(255,69,58,0.4)",
                      }}
                    />
                  </div>
                  <p className="text-xs truncate text-text-tertiary">
                    {intg.detail}
                  </p>
                </div>

                {/* Action button */}
                <Button
                  variant={intg.connected ? "glass" : "default"}
                  size="sm"
                  className="flex-shrink-0"
                  onClick={() => {
                    if (["youtube", "instagram", "tiktok"].includes(intg.id)) {
                      window.location.href = "/social";
                    } else if (intg.id === "suno") {
                      setSunoKeyOpen(true);
                      setTimeout(() => document.getElementById("suno-section")?.scrollIntoView({ behavior: "smooth" }), 100);
                    } else if (intg.id === "replicate") {
                      setReplicateKeyOpen(true);
                      setTimeout(() => document.getElementById("replicate-section")?.scrollIntoView({ behavior: "smooth" }), 100);
                    } else if (intg.id === "airbit") {
                      setAirbitOpen(true);
                      setTimeout(() => document.getElementById("airbit-section")?.scrollIntoView({ behavior: "smooth" }), 100);
                    } else if (intg.id === "beatstars") {
                      setBeatstarsOpen(true);
                      setTimeout(() => document.getElementById("beatstars-section")?.scrollIntoView({ behavior: "smooth" }), 100);
                    }
                  }}
                >
                  {intg.actionLabel}
                </Button>
              </div>
            );
          })}
        </div>
      </section>

      {/* ── Suno API Key ───────────────────────────────── */}
      <section id="suno-section" className="mb-10">
        <button
          onClick={() => setSunoKeyOpen(!sunoKeyOpen)}
          className="flex items-center gap-3 w-full text-left mb-4 cursor-pointer"
        >
          <Key
            size={18}
            strokeWidth={1.8}
            className="text-text-tertiary"
          />
          <h2 className="text-lg font-semibold text-foreground">
            Suno API Key
          </h2>
          <ChevronDown
            size={16}
            className={`text-text-tertiary ml-auto transition-transform duration-200 ${
              sunoKeyOpen ? "rotate-180" : ""
            }`}
          />
        </button>

        {sunoKeyOpen && (
          <div className="rounded-lg p-5 bg-card border border-border">
            <p className="text-sm mb-4 text-muted-foreground">
              Enter your Suno API key to enable AI music generation in Studio.
            </p>

            <div className="flex gap-3 mb-4">
              <div className="relative flex-1">
                <input
                  type={sunoKeyVisible ? "text" : "password"}
                  value={sunoKeyInput}
                  onChange={(e) => setSunoKeyInput(e.target.value)}
                  placeholder="sk-..."
                  className="w-full px-4 py-2.5 rounded-md text-sm outline-none transition-all duration-200 pr-10 bg-muted border border-border-light text-foreground focus:border-accent"
                />
                <button
                  onClick={() => setSunoKeyVisible(!sunoKeyVisible)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 cursor-pointer"
                  aria-label={
                    sunoKeyVisible ? "Hide API key" : "Show API key"
                  }
                >
                  {sunoKeyVisible ? (
                    <EyeOff size={16} className="text-text-tertiary" />
                  ) : (
                    <Eye size={16} className="text-text-tertiary" />
                  )}
                </button>
              </div>

              <Button
                onClick={handleSaveSunoKey}
                disabled={savingKey || !sunoKeyInput}
                className={
                  savingKey || !sunoKeyInput
                    ? "bg-muted text-text-tertiary opacity-60"
                    : ""
                }
                size="lg"
              >
                {savingKey && <Loader2 size={14} className="animate-spin" />}
                {savingKey ? "Saving..." : "Save Key"}
              </Button>
            </div>

            <a
              href="https://sunoapi.org"
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1.5 text-xs font-medium transition-all duration-200 text-accent"
            >
              Get your API key from sunoapi.org
              <ExternalLink size={12} />
            </a>
          </div>
        )}
      </section>

      {/* ── Replicate API Key (AI Thumbnails) ─────────── */}
      <section id="replicate-section" className="mb-10">
        <button
          onClick={() => setReplicateKeyOpen(!replicateKeyOpen)}
          className="flex items-center gap-3 w-full text-left mb-4 cursor-pointer"
        >
          <Sparkles
            size={18}
            strokeWidth={1.8}
            className="text-text-tertiary"
          />
          <h2 className="text-lg font-semibold text-foreground">
            Replicate API Token
          </h2>
          <Badge variant="accent" className="ml-1">
            AI Thumbnails
          </Badge>
          <ChevronDown
            size={16}
            className={`text-text-tertiary ml-auto transition-transform duration-200 ${
              replicateKeyOpen ? "rotate-180" : ""
            }`}
          />
        </button>

        {replicateKeyOpen && (
          <div className="rounded-lg p-5 bg-card border border-border animate-fade-in">
            <p className="text-sm mb-4 text-muted-foreground">
              Enter your Replicate API token to enable AI-powered thumbnail generation on beat detail pages.
            </p>

            <div className="flex gap-3 mb-4">
              <div className="relative flex-1">
                <input
                  type={replicateKeyVisible ? "text" : "password"}
                  value={replicateKeyInput}
                  onChange={(e) => setReplicateKeyInput(e.target.value)}
                  placeholder="r8_..."
                  className="w-full px-4 py-2.5 rounded-md text-sm outline-none transition-all duration-200 pr-10 bg-muted border border-border-light text-foreground focus:border-accent"
                />
                <button
                  onClick={() => setReplicateKeyVisible(!replicateKeyVisible)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 cursor-pointer"
                  aria-label={
                    replicateKeyVisible ? "Hide API token" : "Show API token"
                  }
                >
                  {replicateKeyVisible ? (
                    <EyeOff size={16} className="text-text-tertiary" />
                  ) : (
                    <Eye size={16} className="text-text-tertiary" />
                  )}
                </button>
              </div>

              <Button
                onClick={handleSaveReplicateKey}
                disabled={savingReplicateKey || !replicateKeyInput}
                className={
                  savingReplicateKey || !replicateKeyInput
                    ? "bg-muted text-text-tertiary opacity-60"
                    : ""
                }
                size="lg"
              >
                {savingReplicateKey && <Loader2 size={14} className="animate-spin" />}
                {savingReplicateKey ? "Saving..." : "Save Token"}
              </Button>
            </div>

            <a
              href="https://replicate.com/account/api-tokens"
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1.5 text-xs font-medium transition-all duration-200 text-accent"
            >
              Get your API token from replicate.com
              <ExternalLink size={12} />
            </a>
          </div>
        )}
      </section>

      {/* ── Beat Stores ───────────────────────────────── */}
      <section className="mb-10">
        {/* Airbit */}
        <button
          id="airbit-section"
          onClick={() => setAirbitOpen(!airbitOpen)}
          className="flex items-center gap-3 w-full text-left mb-4 cursor-pointer"
        >
          <ShoppingBag size={18} strokeWidth={1.8} className="text-text-tertiary" />
          <h2 className="text-lg font-semibold text-foreground">Airbit</h2>
          <Badge variant="accent" className="ml-1">Beat Store</Badge>
          <ChevronDown
            size={16}
            className={`text-text-tertiary ml-auto transition-transform duration-200 ${airbitOpen ? "rotate-180" : ""}`}
          />
        </button>
        {airbitOpen && (
          <div className="rounded-lg p-5 bg-card border border-border animate-fade-in mb-6">
            <p className="text-sm mb-4 text-muted-foreground">
              Connect your Airbit store to upload beats directly from the dashboard.
            </p>
            <div className="space-y-3 mb-4">
              <input
                type="email"
                value={airbitEmail}
                onChange={(e) => setAirbitEmail(e.target.value)}
                placeholder="Airbit email"
                className="w-full px-4 py-2.5 rounded-md text-sm outline-none bg-muted border border-border-light text-foreground focus:border-accent"
              />
              <div className="relative">
                <input
                  type={airbitKeyVisible ? "text" : "password"}
                  value={airbitKey}
                  onChange={(e) => setAirbitKey(e.target.value)}
                  placeholder="API key"
                  className="w-full px-4 py-2.5 rounded-md text-sm outline-none pr-10 bg-muted border border-border-light text-foreground focus:border-accent"
                />
                <button
                  onClick={() => setAirbitKeyVisible(!airbitKeyVisible)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 cursor-pointer"
                >
                  {airbitKeyVisible ? <EyeOff size={16} className="text-text-tertiary" /> : <Eye size={16} className="text-text-tertiary" />}
                </button>
              </div>
              <input
                type="url"
                value={airbitUrl}
                onChange={(e) => setAirbitUrl(e.target.value)}
                placeholder="Store URL (e.g. https://airbit.com/mystore)"
                className="w-full px-4 py-2.5 rounded-md text-sm outline-none bg-muted border border-border-light text-foreground focus:border-accent"
              />
            </div>
            <div className="flex gap-3">
              <Button onClick={handleSaveAirbit} disabled={savingAirbit || !airbitKey} size="lg">
                {savingAirbit && <Loader2 size={14} className="animate-spin" />}
                {savingAirbit ? "Connecting..." : "Connect Airbit"}
              </Button>
              {integrations.find((i) => i.id === "airbit")?.connected && (
                <Button
                  onClick={() => handleDisconnectStore("airbit")}
                  variant="outline"
                  size="lg"
                  className="text-red-400 border-red-400/30 hover:bg-red-400/10"
                >
                  Disconnect
                </Button>
              )}
            </div>
          </div>
        )}

        {/* BeatStars */}
        <button
          id="beatstars-section"
          onClick={() => setBeatstarsOpen(!beatstarsOpen)}
          className="flex items-center gap-3 w-full text-left mb-4 cursor-pointer"
        >
          <Store size={18} strokeWidth={1.8} className="text-text-tertiary" />
          <h2 className="text-lg font-semibold text-foreground">BeatStars</h2>
          <Badge variant="accent" className="ml-1">Beat Store</Badge>
          <ChevronDown
            size={16}
            className={`text-text-tertiary ml-auto transition-transform duration-200 ${beatstarsOpen ? "rotate-180" : ""}`}
          />
        </button>
        {beatstarsOpen && (
          <div className="rounded-lg p-5 bg-card border border-border animate-fade-in mb-6">
            <p className="text-sm mb-4 text-muted-foreground">
              Connect your BeatStars store to upload beats directly from the dashboard.
            </p>
            <div className="space-y-3 mb-4">
              <input
                type="email"
                value={beatstarsEmail}
                onChange={(e) => setBeatstarsEmail(e.target.value)}
                placeholder="BeatStars email"
                className="w-full px-4 py-2.5 rounded-md text-sm outline-none bg-muted border border-border-light text-foreground focus:border-accent"
              />
              <div className="relative">
                <input
                  type={beatstarsKeyVisible ? "text" : "password"}
                  value={beatstarsKey}
                  onChange={(e) => setBeatstarsKey(e.target.value)}
                  placeholder="API key / session token"
                  className="w-full px-4 py-2.5 rounded-md text-sm outline-none pr-10 bg-muted border border-border-light text-foreground focus:border-accent"
                />
                <button
                  onClick={() => setBeatstarsKeyVisible(!beatstarsKeyVisible)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 cursor-pointer"
                >
                  {beatstarsKeyVisible ? <EyeOff size={16} className="text-text-tertiary" /> : <Eye size={16} className="text-text-tertiary" />}
                </button>
              </div>
              <input
                type="url"
                value={beatstarsUrl}
                onChange={(e) => setBeatstarsUrl(e.target.value)}
                placeholder="Store URL (e.g. https://beatstars.com/mystore)"
                className="w-full px-4 py-2.5 rounded-md text-sm outline-none bg-muted border border-border-light text-foreground focus:border-accent"
              />
            </div>
            <div className="flex gap-3">
              <Button onClick={handleSaveBeatstars} disabled={savingBeatstars || !beatstarsKey} size="lg">
                {savingBeatstars && <Loader2 size={14} className="animate-spin" />}
                {savingBeatstars ? "Connecting..." : "Connect BeatStars"}
              </Button>
              {integrations.find((i) => i.id === "beatstars")?.connected && (
                <Button
                  onClick={() => handleDisconnectStore("beatstars")}
                  variant="outline"
                  size="lg"
                  className="text-red-400 border-red-400/30 hover:bg-red-400/10"
                >
                  Disconnect
                </Button>
              )}
            </div>
          </div>
        )}

        {/* Default Beat Pricing */}
        <button
          onClick={() => setPricingOpen(!pricingOpen)}
          className="flex items-center gap-3 w-full text-left mb-4 cursor-pointer"
        >
          <DollarSign size={18} strokeWidth={1.8} className="text-text-tertiary" />
          <h2 className="text-lg font-semibold text-foreground">Default Beat Pricing</h2>
          <ChevronDown
            size={16}
            className={`text-text-tertiary ml-auto transition-transform duration-200 ${pricingOpen ? "rotate-180" : ""}`}
          />
        </button>
        {pricingOpen && (
          <div className="rounded-lg p-5 bg-card border border-border animate-fade-in mb-6">
            <p className="text-sm mb-4 text-muted-foreground">
              Set default pricing for new beat listings. Individual beats can override these.
            </p>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mb-4">
              <div>
                <label className="text-xs font-medium text-muted-foreground mb-1 block">Basic License</label>
                <div className="relative">
                  <DollarSign size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-text-tertiary" />
                  <input
                    type="number"
                    value={basicPrice}
                    onChange={(e) => setBasicPrice(parseFloat(e.target.value) || 0)}
                    step="0.01"
                    className="w-full pl-8 pr-3 py-2.5 rounded-md text-sm outline-none bg-muted border border-border-light text-foreground focus:border-accent"
                  />
                </div>
              </div>
              <div>
                <label className="text-xs font-medium text-muted-foreground mb-1 block">Premium License</label>
                <div className="relative">
                  <DollarSign size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-text-tertiary" />
                  <input
                    type="number"
                    value={premiumPrice}
                    onChange={(e) => setPremiumPrice(parseFloat(e.target.value) || 0)}
                    step="0.01"
                    className="w-full pl-8 pr-3 py-2.5 rounded-md text-sm outline-none bg-muted border border-border-light text-foreground focus:border-accent"
                  />
                </div>
              </div>
              <div>
                <label className="text-xs font-medium text-muted-foreground mb-1 block">Exclusive License</label>
                <div className="relative">
                  <DollarSign size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-text-tertiary" />
                  <input
                    type="number"
                    value={exclusivePrice}
                    onChange={(e) => setExclusivePrice(parseFloat(e.target.value) || 0)}
                    step="0.01"
                    className="w-full pl-8 pr-3 py-2.5 rounded-md text-sm outline-none bg-muted border border-border-light text-foreground focus:border-accent"
                  />
                </div>
              </div>
            </div>
            <Button onClick={handleSavePricing} disabled={savingPricing} size="lg">
              {savingPricing && <Loader2 size={14} className="animate-spin" />}
              {savingPricing ? "Saving..." : "Save Pricing"}
            </Button>
          </div>
        )}
      </section>

      {/* ── Pipeline Settings ──────────────────────────── */}
      <section className="mb-10">
        <h2 className="text-lg font-semibold mb-4 text-foreground">
          Pipeline Settings
        </h2>
        <div className="rounded-lg bg-card border border-border overflow-visible">
          {/* Default privacy */}
          <div className="flex items-center justify-between px-5 py-4 border-b border-border">
            <div>
              <p className="text-sm font-medium text-foreground">
                Default Privacy
              </p>
              <p className="text-xs mt-0.5 text-text-tertiary">
                Privacy setting for new uploads
              </p>
            </div>
            <div className="relative">
              <button
                onClick={() => setPrivacyOpen(!privacyOpen)}
                className="flex items-center gap-2 px-4 py-2 rounded-md text-sm font-medium cursor-pointer transition-all duration-200 bg-muted border border-border-light text-foreground"
                style={{ minWidth: 130 }}
              >
                <span className="flex-1 text-left">
                  {privacyOptions.find((o) => o.value === privacy)?.label}
                </span>
                <ChevronDown
                  size={14}
                  className={`text-text-tertiary transition-transform duration-200 ${
                    privacyOpen ? "rotate-180" : ""
                  }`}
                />
              </button>
              {privacyOpen && (
                <div
                  className="absolute right-0 top-full mt-1 rounded-lg overflow-hidden z-10 bg-card border border-border-light shadow-lg"
                  style={{ minWidth: 130 }}
                >
                  {privacyOptions.map((opt) => (
                    <button
                      key={opt.value}
                      onClick={() => {
                        updateSetting("defaultPrivacy", opt.value);
                        setPrivacyOpen(false);
                      }}
                      className={`w-full text-left px-4 py-2.5 text-sm cursor-pointer transition-all duration-150 ${
                        privacy === opt.value
                          ? "text-accent bg-accent-muted"
                          : "text-foreground hover:bg-muted"
                      }`}
                    >
                      {opt.label}
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* Default artist name */}
          <div className="flex items-center justify-between px-5 py-4 border-b border-border">
            <div>
              <p className="text-sm font-medium text-foreground">
                Default Artist Name
              </p>
              <p className="text-xs mt-0.5 text-text-tertiary">
                Used in metadata and SEO tags
              </p>
            </div>
            <input
              type="text"
              value={artistName}
              onChange={(e) => updateSetting("artistName", e.target.value)}
              className="px-4 py-2 rounded-md text-sm outline-none transition-all duration-200 text-right bg-muted border border-border-light text-foreground focus:border-accent"
              style={{ width: 180 }}
            />
          </div>

          {/* Pipeline defaults note */}
          <div className="px-5 py-3">
            <p className="text-[11px] text-text-tertiary">
              These defaults are used by the Dashboard quick actions. Pipeline page has its own privacy selector.
            </p>
          </div>
        </div>
      </section>

      {/* ── Schedule Settings ──────────────────────────── */}
      <section className="mb-10">
        <div className="flex items-center gap-3 mb-4">
          <Calendar
            size={18}
            strokeWidth={1.8}
            className="text-text-tertiary"
          />
          <h2 className="text-lg font-semibold text-foreground">
            Schedule Settings
          </h2>
        </div>
        <div className="rounded-lg bg-card border border-border overflow-visible">
          {/* Uploads per day */}
          <div className="flex items-center justify-between px-5 py-4 border-b border-border">
            <div>
              <p className="text-sm font-medium text-foreground">
                Uploads Per Day
              </p>
              <p className="text-xs mt-0.5 text-text-tertiary">
                How many videos to upload each day
              </p>
            </div>
            <div className="flex items-center gap-2">
              <button
                onClick={() => {
                  const current = scheduleSettings?.daily_yt_count ?? 2;
                  if (current > 1) updateScheduleSettings({ daily_yt_count: current - 1 });
                }}
                className="w-7 h-7 rounded-lg flex items-center justify-center bg-muted border border-border-light text-foreground hover:bg-muted/80 transition-colors cursor-pointer text-sm font-bold"
              >
                -
              </button>
              <span className="text-base font-bold text-foreground tabular-nums w-6 text-center">
                {scheduleSettings?.daily_yt_count ?? 2}
              </span>
              <button
                onClick={() => {
                  const current = scheduleSettings?.daily_yt_count ?? 2;
                  if (current < 10) updateScheduleSettings({ daily_yt_count: current + 1 });
                }}
                className="w-7 h-7 rounded-lg flex items-center justify-center bg-muted border border-border-light text-foreground hover:bg-muted/80 transition-colors cursor-pointer text-sm font-bold"
              >
                +
              </button>
            </div>
          </div>

          {/* Upload times */}
          <div className="px-5 py-4 border-b border-border">
            <div className="flex items-center justify-between mb-3">
              <div>
                <p className="text-sm font-medium text-foreground">
                  Upload Times (EST)
                </p>
                <p className="text-xs mt-0.5 text-text-tertiary">
                  Times when videos go live each day
                </p>
              </div>
              <button
                onClick={() => setSchedEditingTimes(!schedEditingTimes)}
                className="text-xs font-medium text-accent hover:opacity-80 transition-opacity cursor-pointer"
              >
                {schedEditingTimes ? "Done" : "Edit"}
              </button>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              {(scheduleSettings?.yt_times_est ?? ["11:00", "18:00"]).map((t) => {
                const [h, m] = t.split(":").map(Number);
                const ampm = h >= 12 ? "PM" : "AM";
                const h12 = h === 0 ? 12 : h > 12 ? h - 12 : h;
                const label = `${h12}:${m.toString().padStart(2, "0")} ${ampm}`;
                return (
                  <div
                    key={t}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-accent-muted text-accent text-sm font-medium"
                  >
                    <Clock size={12} />
                    {label}
                    {schedEditingTimes && (
                      <button
                        onClick={async () => {
                          const remaining = (scheduleSettings?.yt_times_est ?? []).filter(
                            (x) => x !== t
                          );
                          if (remaining.length === 0) {
                            toast("Must have at least one time slot", "error");
                            return;
                          }
                          await updateScheduleSettings({ yt_times_est: remaining });
                          toast(`Removed ${label}`, "success");
                        }}
                        className="ml-0.5 hover:opacity-70 transition-opacity cursor-pointer"
                      >
                        <XIcon size={12} />
                      </button>
                    )}
                  </div>
                );
              })}
              {schedEditingTimes && (
                <div className="flex items-center gap-2">
                  <input
                    type="time"
                    value={schedNewTime}
                    onChange={(e) => setSchedNewTime(e.target.value)}
                    className="rounded-lg px-3 py-1.5 text-sm outline-none bg-muted border border-border-light text-foreground"
                    style={{ colorScheme: "dark" }}
                  />
                  <Button
                    onClick={async () => {
                      const existing = scheduleSettings?.yt_times_est ?? [];
                      if (existing.includes(schedNewTime)) {
                        toast("Time already exists", "error");
                        return;
                      }
                      await updateScheduleSettings({
                        yt_times_est: [...existing, schedNewTime].sort(),
                      });
                      const [h2, m2] = schedNewTime.split(":").map(Number);
                      const ap = h2 >= 12 ? "PM" : "AM";
                      const h122 = h2 === 0 ? 12 : h2 > 12 ? h2 - 12 : h2;
                      toast(`Added ${h122}:${m2.toString().padStart(2, "0")} ${ap}`, "success");
                    }}
                    variant="ghost"
                    size="sm"
                    className="text-accent"
                  >
                    <Plus size={12} />
                    Add
                  </Button>
                </div>
              )}
            </div>
          </div>

          {/* Buffer warning days */}
          <div className="flex items-center justify-between px-5 py-4 border-b border-border">
            <div>
              <p className="text-sm font-medium text-foreground">
                Buffer Warning
              </p>
              <p className="text-xs mt-0.5 text-text-tertiary">
                Warn when queue has fewer than this many days of content
              </p>
            </div>
            <div className="flex items-center gap-2">
              <input
                type="number"
                min={1}
                max={30}
                value={scheduleSettings?.buffer_warning_days ?? 7}
                onChange={(e) =>
                  updateScheduleSettings({
                    buffer_warning_days: Math.max(1, Math.min(30, Number(e.target.value))),
                  })
                }
                className="w-16 rounded-md px-3 py-2 text-sm text-center outline-none bg-muted border border-border-light text-foreground"
              />
              <span className="text-xs text-text-tertiary">days</span>
            </div>
          </div>

          {/* Autopilot */}
          <div className="flex items-center justify-between px-5 py-4">
            <div>
              <p className="text-sm font-medium text-foreground">
                Autopilot
              </p>
              <p className="text-xs mt-0.5 text-text-tertiary">
                Automatically schedule queued beats at configured times
              </p>
            </div>
            <Switch
              checked={scheduleSettings?.autopilot_enabled ?? true}
              onCheckedChange={(checked) =>
                updateScheduleSettings({ autopilot_enabled: checked })
              }
            />
          </div>
        </div>
      </section>

      {/* ── User Management (admin only) ────────────────── */}
      {isAdmin && (
        <section className="mb-10">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-3">
              <Users
                size={18}
                strokeWidth={1.8}
                className="text-text-tertiary"
              />
              <h2 className="text-lg font-semibold text-foreground">
                User Management
              </h2>
              <Badge variant="accent">
                Admin
              </Badge>
            </div>
            <Button
              onClick={() => {
                setShowAddForm(!showAddForm);
                setGeneratedPassword("");
              }}
              variant={showAddForm ? "glass" : "default"}
              size="sm"
              className="hover:opacity-85"
            >
              <UserPlus size={14} />
              {showAddForm ? "Cancel" : "Add Producer"}
            </Button>
          </div>

          {/* Add producer form */}
          {showAddForm && (
            <div className="rounded-lg p-5 mb-4 animate-fade-in bg-card border border-accent">
              <p className="text-sm font-medium mb-4 text-foreground">
                Create Producer Account
              </p>

              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mb-4">
                <input
                  type="text"
                  value={newUsername}
                  onChange={(e) => setNewUsername(e.target.value)}
                  placeholder="Username"
                  className="px-4 py-2.5 rounded-md text-sm outline-none transition-all duration-200 bg-muted border border-border-light text-foreground focus:border-accent"
                />
                <input
                  type="text"
                  value={newDisplayName}
                  onChange={(e) => setNewDisplayName(e.target.value)}
                  placeholder="Display Name (optional)"
                  className="px-4 py-2.5 rounded-md text-sm outline-none transition-all duration-200 bg-muted border border-border-light text-foreground focus:border-accent"
                />
                <input
                  type="text"
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  placeholder="Password (auto-generated if empty)"
                  className="px-4 py-2.5 rounded-md text-sm outline-none transition-all duration-200 bg-muted border border-border-light text-foreground focus:border-accent"
                />
              </div>

              <Button
                onClick={handleCreateUser}
                disabled={creatingUser || !newUsername.trim()}
                className={
                  creatingUser || !newUsername.trim()
                    ? "bg-muted text-text-tertiary opacity-60"
                    : ""
                }
                size="lg"
              >
                {creatingUser && <Loader2 size={14} className="animate-spin" />}
                {creatingUser ? "Creating..." : "Create Producer"}
              </Button>

              {/* Show generated password */}
              {generatedPassword && (
                <div className="mt-4 p-3 rounded-lg flex items-center justify-between bg-accent-muted border border-accent">
                  <div>
                    <p className="text-xs font-medium mb-1 text-accent">
                      Password (share with producer):
                    </p>
                    <code className="text-sm font-mono font-bold text-foreground">
                      {generatedPassword}
                    </code>
                  </div>
                  <Button
                    onClick={() => copyToClipboard(generatedPassword)}
                    variant="ghost"
                    size="icon-sm"
                    className="text-accent"
                    title="Copy password"
                  >
                    <Copy size={16} />
                  </Button>
                </div>
              )}
            </div>
          )}

          {/* Producer list */}
          <div className="rounded-lg bg-card border border-border overflow-visible">
            {producers.length === 0 ? (
              <div className="px-5 py-8 text-center text-text-tertiary">
                <Users
                  size={32}
                  strokeWidth={1.2}
                  className="mx-auto mb-3 opacity-40"
                />
                <p className="text-sm font-medium">No producers yet</p>
                <p className="text-xs mt-1">
                  Click &quot;Add Producer&quot; to create an account
                </p>
              </div>
            ) : (
              producers.map((user, i) => (
                <div
                  key={user.username}
                  className={`flex items-center gap-4 px-5 py-3.5 ${
                    i < producers.length - 1 ? "border-b border-border" : ""
                  }`}
                >
                  {/* Avatar */}
                  <div className="w-9 h-9 rounded-full flex items-center justify-center flex-shrink-0 text-xs font-bold uppercase bg-accent-muted text-accent">
                    {(user.display_name || user.username).charAt(0)}
                  </div>

                  {/* Info */}
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium truncate text-foreground">
                      {user.display_name || user.username}
                    </p>
                    <p className="text-xs truncate text-text-tertiary">
                      @{user.username}
                      {user.created_at && (
                        <span className="ml-2">
                          · joined{" "}
                          {new Date(user.created_at).toLocaleDateString()}
                        </span>
                      )}
                    </p>
                  </div>

                  {/* Role badge */}
                  <span className="text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-md flex-shrink-0 bg-muted text-text-tertiary">
                    {user.role}
                  </span>

                  {/* Delete button */}
                  <Button
                    onClick={() => handleDeleteUser(user.username)}
                    disabled={deletingUser === user.username}
                    variant="ghost"
                    size="icon-sm"
                    className="flex-shrink-0 text-text-tertiary hover:bg-error-muted hover:text-error"
                    title={`Delete ${user.username}`}
                  >
                    {deletingUser === user.username ? (
                      <Loader2 size={16} className="animate-spin" />
                    ) : (
                      <Trash2 size={16} />
                    )}
                  </Button>
                </div>
              ))
            )}
          </div>
        </section>
      )}

      {/* ── System Info ────────────────────────────────── */}
      <section className="mb-6">
        <h2 className="text-lg font-semibold mb-4 text-foreground">
          System Info
        </h2>
        <div className="rounded-lg bg-card border border-border overflow-visible">
          {[
            {
              icon: Server,
              label: "API Status",
              value: "Connected",
              valueClass: "text-success",
            },
            {
              icon: Info,
              label: "Version",
              value: "FY3 Automation Center v1.0",
              valueClass: "text-muted-foreground",
            },
            {
              icon: FolderOpen,
              label: "Beats Directory",
              value: "~/yt_automation/beats/",
              valueClass: "text-muted-foreground",
            },
            {
              icon: FolderOpen,
              label: "Output Directory",
              value: "~/yt_automation/output/",
              valueClass: "text-muted-foreground",
            },
          ].map((row, i, arr) => {
            const RowIcon = row.icon;
            return (
              <div
                key={row.label}
                className={`flex items-center justify-between px-5 py-3.5 ${
                  i < arr.length - 1 ? "border-b border-border" : ""
                }`}
              >
                <div className="flex items-center gap-3">
                  <RowIcon
                    size={16}
                    strokeWidth={1.8}
                    className="text-text-tertiary"
                  />
                  <span className="text-sm text-muted-foreground">
                    {row.label}
                  </span>
                </div>
                <span className={`text-sm font-medium ${row.valueClass}`}>
                  {row.value}
                </span>
              </div>
            );
          })}
        </div>
      </section>

      {/* ── Cache Management ────────────────────────────── */}
      <section className="mb-10">
        <h2 className="text-lg font-semibold mb-4 text-foreground">
          Cache & Storage
        </h2>
        <div
          className="rounded-2xl p-6"
          style={{
            background: "var(--bg-card)",
            border: "1px solid var(--glass-border)",
          }}
        >
          <div className="flex items-start gap-4">
            <div
              className="w-11 h-11 rounded-xl flex items-center justify-center flex-shrink-0"
              style={{ background: "var(--warning-muted)" }}
            >
              <RefreshCw size={20} style={{ color: "var(--warning)" }} />
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-sm font-semibold text-foreground mb-1">
                Clear App Cache
              </p>
              <p className="text-xs text-text-tertiary mb-4" style={{ lineHeight: 1.5 }}>
                Clears cached data, service workers, and session storage. Your login and theme preference will be preserved. Use this if the app feels stuck or isn&apos;t loading properly after an update.
              </p>
              <Button
                variant="outline"
                size="sm"
                onClick={async () => {
                  try {
                    if ("caches" in window) {
                      const names = await caches.keys();
                      await Promise.all(names.map((n) => caches.delete(n)));
                    }
                    if ("serviceWorker" in navigator) {
                      const regs = await navigator.serviceWorker.getRegistrations();
                      await Promise.all(regs.map((r) => r.unregister()));
                    }
                  } catch { /* best effort */ }
                  const keysToKeep = ["fy3-token", "fy3-theme"];
                  for (let i = localStorage.length - 1; i >= 0; i--) {
                    const k = localStorage.key(i);
                    if (k && !keysToKeep.includes(k)) localStorage.removeItem(k);
                  }
                  sessionStorage.clear();
                  window.location.reload();
                }}
                className="gap-2"
              >
                <Trash2 size={14} />
                Clear Cache & Reload
              </Button>
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}
