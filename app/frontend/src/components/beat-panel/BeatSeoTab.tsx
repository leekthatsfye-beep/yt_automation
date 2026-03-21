"use client";

import { useState, useEffect } from "react";
import { Sparkles, Save, Loader2, CheckCircle2, X, Plus } from "lucide-react";
import { api } from "@/hooks/useApi";
import { useToast } from "@/components/ToastProvider";
import type { Beat } from "@/types/beat";

interface Props {
  beat: Beat;
  onUpdated: () => void;
}

export default function BeatSeoTab({ beat, onUpdated }: Props) {
  const { toast } = useToast();
  const [title, setTitle] = useState(beat.title);
  const [description, setDescription] = useState(beat.description);
  const [tags, setTags] = useState<string[]>([...beat.tags]);
  const [newTag, setNewTag] = useState("");
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [generating, setGenerating] = useState(false);

  useEffect(() => {
    setTitle(beat.title);
    setDescription(beat.description);
    setTags([...beat.tags]);
    setDirty(false);
  }, [beat.stem]);

  const markDirty = () => setDirty(true);

  const addTag = () => {
    const t = newTag.trim();
    if (t && !tags.includes(t)) {
      setTags([...tags, t]);
      setNewTag("");
      markDirty();
    }
  };

  const removeTag = (tag: string) => {
    setTags(tags.filter((t) => t !== tag));
    markDirty();
  };

  const handleGenerate = async () => {
    setGenerating(true);
    try {
      await api.post(`/beats/${beat.stem}/generate-seo`);
      toast("SEO metadata generated", "success");
      onUpdated();
    } catch {
      toast("SEO generation failed", "error");
    } finally {
      setGenerating(false);
    }
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      await api.put(`/beats/${beat.stem}/metadata`, { title, artist: beat.artist, description, tags });
      setDirty(false);
      toast("SEO saved", "success");
      onUpdated();
    } catch {
      toast("Failed to save", "error");
    } finally {
      setSaving(false);
    }
  };

  const hasSeo = beat.description && beat.tags.length > 0;

  return (
    <div className="space-y-5">
      {/* SEO Status Banner */}
      <div
        className="flex items-center gap-3 p-4 rounded-xl"
        style={{
          background: hasSeo ? "var(--success-muted)" : "var(--warning-muted)",
          border: `1px solid ${hasSeo ? "var(--success)" : "var(--warning)"}20`,
        }}
      >
        <div
          className="w-8 h-8 rounded-lg flex items-center justify-center"
          style={{ background: hasSeo ? "var(--success)" : "var(--warning)", opacity: 0.15 }}
        >
          {hasSeo ? <CheckCircle2 size={16} style={{ color: "var(--success)" }} /> : <Sparkles size={16} style={{ color: "var(--warning)" }} />}
        </div>
        <div className="flex-1">
          <p className="text-sm font-semibold" style={{ color: hasSeo ? "var(--success)" : "var(--warning)" }}>
            {hasSeo ? "SEO Optimized" : "Missing SEO"}
          </p>
          <p className="text-xs text-text-tertiary">
            {hasSeo ? `${tags.length} tags, ${description.length} char description` : "Generate SEO metadata to optimize discoverability"}
          </p>
        </div>
      </div>

      {/* AI Generate Button */}
      <button
        onClick={handleGenerate}
        disabled={generating}
        className="w-full py-3 rounded-xl text-sm font-semibold flex items-center justify-center gap-2 transition-all duration-200 cursor-pointer btn-gradient"
        style={generating ? { opacity: 0.6, cursor: "not-allowed" } : {}}
      >
        {generating ? <Loader2 size={15} className="animate-spin" /> : <Sparkles size={15} />}
        {generating ? "Generating SEO..." : "Generate SEO with AI"}
      </button>

      {/* Title */}
      <div>
        <div className="flex items-center justify-between mb-1.5">
          <label className="text-xs font-semibold uppercase tracking-wider text-text-tertiary">Title</label>
          <span className="text-[10px] tabular-nums text-text-tertiary">{title.length}/100</span>
        </div>
        <input
          value={title}
          onChange={(e) => { setTitle(e.target.value); markDirty(); }}
          className="w-full px-3 py-2 rounded-lg text-sm bg-bg-hover border border-border text-foreground outline-none focus:border-accent transition-colors"
          placeholder="SEO-optimized title"
          maxLength={100}
        />
      </div>

      {/* Description */}
      <div>
        <div className="flex items-center justify-between mb-1.5">
          <label className="text-xs font-semibold uppercase tracking-wider text-text-tertiary">Description</label>
          <span className="text-[10px] tabular-nums text-text-tertiary">{description.length}/5000</span>
        </div>
        <textarea
          value={description}
          onChange={(e) => { setDescription(e.target.value); markDirty(); }}
          rows={6}
          className="w-full px-3 py-2 rounded-lg text-sm bg-bg-hover border border-border text-foreground outline-none focus:border-accent transition-colors resize-none"
          placeholder="YouTube description with keywords..."
          maxLength={5000}
        />
      </div>

      {/* Tags */}
      <div>
        <div className="flex items-center justify-between mb-1.5">
          <label className="text-xs font-semibold uppercase tracking-wider text-text-tertiary">Tags</label>
          <span className="text-[10px] tabular-nums text-text-tertiary">{tags.length} tags</span>
        </div>
        <div className="flex flex-wrap gap-1.5 mb-2">
          {tags.map((tag) => (
            <span
              key={tag}
              className="inline-flex items-center gap-1 text-xs font-medium px-2 py-1 rounded-md"
              style={{ background: "var(--accent-muted)", color: "var(--accent)" }}
            >
              {tag}
              <button onClick={() => removeTag(tag)} className="hover:text-foreground cursor-pointer">
                <X size={10} />
              </button>
            </span>
          ))}
        </div>
        <div className="flex gap-2">
          <input
            value={newTag}
            onChange={(e) => setNewTag(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && (e.preventDefault(), addTag())}
            placeholder="Add tag..."
            className="flex-1 px-3 py-1.5 rounded-lg text-xs bg-bg-hover border border-border text-foreground outline-none focus:border-accent transition-colors"
          />
          <button onClick={addTag} className="px-3 py-1.5 rounded-lg text-xs font-medium bg-bg-hover border border-border text-text-secondary hover:text-foreground transition-colors cursor-pointer">
            <Plus size={12} />
          </button>
        </div>
      </div>

      {/* Save */}
      {dirty && (
        <button
          onClick={handleSave}
          disabled={saving}
          className="w-full py-2.5 rounded-xl text-sm font-semibold flex items-center justify-center gap-2 transition-all duration-200 cursor-pointer"
          style={{
            background: "linear-gradient(135deg, var(--accent), color-mix(in srgb, var(--accent) 70%, #8b5cf6))",
            color: "#fff",
            opacity: saving ? 0.6 : 1,
          }}
        >
          {saving ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
          {saving ? "Saving..." : "Save SEO"}
        </button>
      )}
    </div>
  );
}
