"use client";

import {
  createContext,
  useContext,
  useState,
  useCallback,
  useEffect,
  type ReactNode,
} from "react";

// ── Types ──────────────────────────────────────────────────────────────

export interface User {
  username: string;
  role: "admin" | "producer";
  display_name?: string;
}

interface AuthContextValue {
  user: User | null;
  token: string | null;
  loading: boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => void;
  isAdmin: boolean;
}

// ── Context ────────────────────────────────────────────────────────────

const AuthContext = createContext<AuthContextValue>({
  user: null,
  token: null,
  loading: true,
  login: async () => {},
  logout: () => {},
  isAdmin: false,
});

export function useAuth() {
  return useContext(AuthContext);
}

// ── Provider ───────────────────────────────────────────────────────────

const TOKEN_KEY = "fy3-token";

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  // Validate token on mount — with timeout to prevent infinite loading
  useEffect(() => {
    const savedToken = localStorage.getItem(TOKEN_KEY);
    if (!savedToken) {
      setLoading(false);
      return;
    }

    let done = false;

    // Hard timeout: if auth check takes more than 6s, give up
    const timeout = setTimeout(() => {
      if (!done) {
        done = true;
        localStorage.removeItem(TOKEN_KEY);
        setLoading(false);
      }
    }, 6000);

    // Validate with backend
    fetch("/api/auth/me", {
      headers: { Authorization: `Bearer ${savedToken}` },
    })
      .then((res) => {
        if (!res.ok) throw new Error("Invalid token");
        return res.json();
      })
      .then((data) => {
        if (done) return;
        done = true;
        clearTimeout(timeout);
        setToken(savedToken);
        setUser({
          username: data.username,
          role: data.role,
          display_name: data.display_name,
        });
      })
      .catch(() => {
        if (done) return;
        done = true;
        clearTimeout(timeout);
        localStorage.removeItem(TOKEN_KEY);
      })
      .finally(() => setLoading(false));

    return () => clearTimeout(timeout);
  }, []);

  const login = useCallback(async (username: string, password: string) => {
    const res = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });

    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data.detail || "Login failed");
    }

    const data = await res.json();
    localStorage.setItem(TOKEN_KEY, data.token);
    setToken(data.token);
    setUser(data.user);
  }, []);

  const logout = useCallback(() => {
    localStorage.removeItem(TOKEN_KEY);
    setToken(null);
    setUser(null);
  }, []);

  return (
    <AuthContext.Provider
      value={{
        user,
        token,
        loading,
        login,
        logout,
        isAdmin: user?.role === "admin",
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}
