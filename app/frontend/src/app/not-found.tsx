"use client";

import { useRouter } from "next/navigation";
import { Home, ArrowLeft } from "lucide-react";

export default function NotFound() {
  const router = useRouter();

  return (
    <div
      className="flex items-center justify-center"
      style={{ minHeight: "60vh", padding: "2rem" }}
    >
      <div
        className="w-full max-w-sm rounded-2xl p-8 text-center"
        style={{
          background: "var(--bg-card)",
          border: "1px solid var(--glass-border)",
          boxShadow: "0 8px 32px rgba(0, 0, 0, 0.2)",
        }}
      >
        <div
          className="w-14 h-14 rounded-xl flex items-center justify-center mx-auto mb-5"
          style={{ background: "var(--accent-muted)" }}
        >
          <span style={{ fontSize: 24 }}>🔍</span>
        </div>

        <h2
          className="text-lg font-semibold mb-2"
          style={{ color: "var(--text-primary)", letterSpacing: "-0.02em" }}
        >
          Page Not Found
        </h2>

        <p
          className="text-sm mb-6"
          style={{ color: "var(--text-tertiary)" }}
        >
          This page doesn&apos;t exist or may have been moved.
        </p>

        <div className="flex items-center justify-center gap-3">
          <button
            onClick={() => router.back()}
            className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-medium transition-all duration-200 cursor-pointer"
            style={{
              background: "var(--bg-hover)",
              color: "var(--text-secondary)",
              border: "1px solid var(--border)",
            }}
          >
            <ArrowLeft size={14} />
            Go Back
          </button>
          <button
            onClick={() => router.push("/dashboard")}
            className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-semibold transition-all duration-200 cursor-pointer"
            style={{
              background: "var(--accent)",
              color: "#ffffff",
            }}
          >
            <Home size={14} />
            Dashboard
          </button>
        </div>
      </div>
    </div>
  );
}
