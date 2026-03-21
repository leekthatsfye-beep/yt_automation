"use client";

import { useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/hooks/useAuth";
import { LogIn, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";

export default function LoginPage() {
  const { login } = useAuth();
  const router = useRouter();

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);

    try {
      await login(username, password);
      router.push("/dashboard");
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Login failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-background p-6 relative overflow-hidden">
      {/* Background ambient glow */}
      <div
        className="absolute top-[-20%] left-[10%] w-[500px] h-[500px] rounded-full pointer-events-none"
        style={{
          background: "radial-gradient(circle, var(--accent-muted), transparent 70%)",
          filter: "blur(80px)",
          animation: "glow-pulse 4s ease-in-out infinite",
        }}
      />
      <div
        className="absolute bottom-[-20%] right-[10%] w-[400px] h-[400px] rounded-full pointer-events-none"
        style={{
          background: "radial-gradient(circle, var(--accent-muted), transparent 70%)",
          filter: "blur(80px)",
          animation: "glow-pulse 4s ease-in-out infinite 2s",
        }}
      />

      {/* Login card */}
      <div className="relative z-10 w-full animate-scale-in" style={{ maxWidth: 420 }}>
        <div className="rounded-lg border border-border bg-bg-card p-8 shadow-[0_8px_32px_rgba(0,0,0,0.4)]">
          {/* Logo */}
          <div className="text-center mb-8">
            <div className="w-16 h-16 rounded-lg mx-auto mb-4 flex items-center justify-center bg-accent-muted">
              <div className="flex items-baseline gap-0.5">
                <span className="text-2xl font-bold text-foreground">FY3</span>
                <span className="text-xs font-bold text-accent">!</span>
              </div>
            </div>
            <h1 className="text-xl font-bold tracking-tight text-foreground">
              Welcome Back
            </h1>
            <p className="text-xs font-medium mt-1 text-text-tertiary">
              Sign in to your automation center
            </p>
          </div>

          {/* Form */}
          <form onSubmit={handleSubmit} className="space-y-5">
            {/* Username */}
            <div>
              <label
                htmlFor="username"
                className="block text-xs font-semibold mb-2 text-muted-foreground"
              >
                Username
              </label>
              <input
                id="username"
                type="text"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                autoComplete="username"
                autoFocus
                required
                className="w-full rounded-md text-sm outline-none transition-all duration-200 bg-bg-card-solid border border-border text-foreground px-4 py-3 focus:border-accent focus:ring-1 focus:ring-accent/30 placeholder:text-text-tertiary"
                placeholder="Enter your username"
              />
            </div>

            {/* Password */}
            <div>
              <label
                htmlFor="password"
                className="block text-xs font-semibold mb-2 text-muted-foreground"
              >
                Password
              </label>
              <input
                id="password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="current-password"
                required
                className="w-full rounded-md text-sm outline-none transition-all duration-200 bg-bg-card-solid border border-border text-foreground px-4 py-3 focus:border-accent focus:ring-1 focus:ring-accent/30 placeholder:text-text-tertiary"
                placeholder="Enter your password"
              />
            </div>

            {/* Error */}
            {error && (
              <div className="flex items-center gap-2 text-xs font-medium rounded-lg text-error bg-error-muted px-4 py-3 border border-error/20">
                <div className="w-1.5 h-1.5 rounded-full bg-error flex-shrink-0" />
                {error}
              </div>
            )}

            {/* Submit */}
            <Button
              type="submit"
              disabled={loading || !username || !password}
              className="w-full h-12 text-sm font-semibold shadow-[0_0_20px_var(--accent-muted)]"
            >
              {loading ? (
                <Loader2 size={16} className="animate-spin" />
              ) : (
                <>
                  <LogIn size={16} />
                  Sign In
                </>
              )}
            </Button>
          </form>
        </div>
      </div>
    </div>
  );
}
