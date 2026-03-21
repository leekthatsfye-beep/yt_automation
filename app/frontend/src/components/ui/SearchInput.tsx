"use client";

import { useState, useRef, useEffect } from "react";
import { X, Command } from "lucide-react";

interface SearchInputProps {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  /** "sm" for modals/pickers, "md" default, "lg" for page-level */
  size?: "sm" | "md" | "lg";
  autoFocus?: boolean;
  /** Show ⌘K shortcut hint */
  showShortcut?: boolean;
  className?: string;
}

export default function SearchInput({
  value,
  onChange,
  placeholder = "Search...",
  size = "md",
  autoFocus = false,
  showShortcut = false,
  className = "",
}: SearchInputProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [focused, setFocused] = useState(false);

  // ⌘K shortcut to focus
  useEffect(() => {
    if (!showShortcut) return;
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        inputRef.current?.focus();
      }
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [showShortcut]);

  const sizes = {
    sm: { h: "h-8", text: "text-xs", pl: "pl-3", pr: value ? "pr-7" : "pr-3" },
    md: { h: "h-9", text: "text-sm", pl: "pl-3.5", pr: value ? "pr-9" : showShortcut ? "pr-14" : "pr-3.5" },
    lg: { h: "h-10", text: "text-sm", pl: "pl-4", pr: value ? "pr-10" : showShortcut ? "pr-16" : "pr-4" },
  };
  const s = sizes[size];

  return (
    <div className={`relative group ${className}`}>
      {/* Search container */}
      <div
        className={`relative ${s.h} rounded-xl transition-all duration-200 overflow-hidden`}
        style={{
          background: focused ? "var(--bg-card-solid)" : "var(--bg-card)",
          border: `1px solid ${focused ? "var(--accent)" : "var(--glass-border)"}`,
          boxShadow: focused
            ? "0 0 0 3px var(--accent-muted), 0 4px 16px rgba(0, 0, 0, 0.15)"
            : "0 1px 3px rgba(0, 0, 0, 0.08)",
        }}
      >
        {/* Input */}
        <input
          ref={inputRef}
          type="text"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onFocus={() => setFocused(true)}
          onBlur={() => setFocused(false)}
          placeholder={placeholder}
          autoFocus={autoFocus}
          className={`w-full ${s.h} ${s.pl} ${s.pr} ${s.text} bg-transparent outline-none transition-colors duration-200`}
          style={{
            color: "var(--text-primary)",
            caretColor: "var(--accent)",
          }}
        />

        {/* Clear button — appears when there's text */}
        {value && (
          <button
            onClick={() => { onChange(""); inputRef.current?.focus(); }}
            className="absolute right-2 top-1/2 -translate-y-1/2 p-0.5 rounded-md transition-all duration-150 cursor-pointer"
            style={{
              color: "var(--text-tertiary)",
              background: "var(--bg-hover)",
            }}
            onMouseEnter={(e) => { e.currentTarget.style.color = "var(--text-primary)"; e.currentTarget.style.background = "var(--bg-card-hover)"; }}
            onMouseLeave={(e) => { e.currentTarget.style.color = "var(--text-tertiary)"; e.currentTarget.style.background = "var(--bg-hover)"; }}
          >
            <X size={size === "sm" ? 10 : 12} />
          </button>
        )}

        {/* ⌘K shortcut hint — hidden when text present or focused */}
        {showShortcut && !value && !focused && (
          <div
            className="absolute right-2.5 top-1/2 -translate-y-1/2 flex items-center gap-0.5 pointer-events-none"
          >
            <kbd
              className="flex items-center gap-0.5 px-1.5 py-0.5 rounded-md text-[10px] font-medium"
              style={{
                background: "var(--bg-hover)",
                color: "var(--text-tertiary)",
                border: "1px solid var(--border)",
                fontFamily: "inherit",
              }}
            >
              <Command size={9} strokeWidth={2.5} />K
            </kbd>
          </div>
        )}
      </div>

      {/* Placeholder styling */}
      <style>{`
        input::placeholder {
          color: var(--text-tertiary) !important;
          opacity: 0.7;
        }
      `}</style>
    </div>
  );
}
