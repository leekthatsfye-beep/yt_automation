"use client";

import { useState, useEffect } from "react";
import { Save, Tag, X, Plus, Music, Clock, HardDrive, Calendar, Loader2, CheckCircle2 } from "lucide-react";
import { api } from "@/hooks/useApi";
import { useToast } from "@/components/ToastProvider";
import type { Beat } from "@/types/beat";

interface Props {
  beat: Beat;
  onUpdated: () => void;
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes}B`;
  if (bytes < 1048576) return `${(bytes / 1024).toFixed(1)}KB`;
  return `${(bytes / 1048576).toFixed(1)}MB`;
}

export default function BeatMetadataTab({ beat, onUpdated }: Props) {
  const { toast } = useToast();
  const [beatName, setBeatName] = useState(beat.beat_name || "");
  const [title, setTitle] = useState(beat.title);
  const [artist, setArtist] = useState(beat.artist);
  const [description, setDescription] = useState(beat.description);
  const [tags, setTags] = useState<string[]>([...beat.tags]);
  const [newTag, setNewTag] = useState("");
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    setBeatName(beat.beat_name || "");
    setTitle(beat.title);
    setArtist(beat.artist);
    setDescription(beat.description);
    setTags([...beat.tags]);
    setDirty(false);
    setSaved(false);
  }, [beat.stem]);

  const markDirty = () => { setDirty(true); setSaved(false); };

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

  const save = async () => {
    setSaving(true);
    try {
      await api.put(`/beats/${beat.stem}/metadata`, { title, beat_name: beatName, artist, description, tags });
      setDirty(false);
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
      toast("Metadata saved", "success");
      onUpdated();
    } catch {
      toast("Failed to save", "error");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-5">
      {/* Beat Info Pills */}
      <div className="flex flex-wrap gap-2">
        {beat.bpm && (
          <span className="inline-flex items-center gap-1.5 text-xs font-medium px-2.5 py-1 rounded-lg" style={{ background: "var(--bg-hover)", color: "var(--text-secondary)" }}>
            <Music size={11} /> {beat.bpm} BPM
          </span>
        )}
        {beat.key && (
          <span className="inline-flex items-center gap-1.5 text-xs font-medium px-2.5 py-1 rounded-lg" style={{ background: "var(--bg-hover)", color: "var(--text-secondary)" }}>
            <Tag size={11} /> {beat.key}
          </span>
        )}
        <span className="inline-flex items-center gap-1.5 text-xs font-medium px-2.5 py-1 rounded-lg" style={{ background: "var(--bg-hover)", color: "var(--text-secondary)" }}>
          <HardDrive size={11} /> {formatSize(beat.file_size)}
        </span>
        <span className="inline-flex items-center gap-1.5 text-xs font-medium px-2.5 py-1 rounded-lg" style={{ background: "var(--bg-hover)", color: "var(--text-secondary)" }}>
          <Calendar size={11} /> {new Date(beat.modified).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })}
        </span>
      </div>

      {/* Beat Name */}
      <div>
        <label className="text-xs font-semibold uppercase tracking-wider text-text-tertiary mb-1.5 block">Beat Name</label>
        <input
          value={beatName}
          onChange={(e) => { setBeatName(e.target.value); markDirty(); }}
          className="w-full px-3 py-2 rounded-lg text-sm bg-bg-hover border border-border text-foreground outline-none focus:border-accent transition-colors"
          placeholder="Display name (e.g. Paul Walker)"
        />
        <p className="text-[10px] mt-1" style={{ color: "var(--text-tertiary)" }}>
          Short name shown across the app &amp; synced to Airbit store
        </p>
      </div>

      {/* Title */}
      <div>
        <label className="text-xs font-semibold uppercase tracking-wider text-text-tertiary mb-1.5 block">Title</label>
        <input
          value={title}
          onChange={(e) => { setTitle(e.target.value); markDirty(); }}
          className="w-full px-3 py-2 rounded-lg text-sm bg-bg-hover border border-border text-foreground outline-none focus:border-accent transition-colors"
          placeholder="Full SEO title"
        />
      </div>

      {/* Artist */}
      <div>
        <label className="text-xs font-semibold uppercase tracking-wider text-text-tertiary mb-1.5 block">Artist</label>
        <input
          value={artist}
          onChange={(e) => { setArtist(e.target.value); markDirty(); }}
          className="w-full px-3 py-2 rounded-lg text-sm bg-bg-hover border border-border text-foreground outline-none focus:border-accent transition-colors"
          placeholder="Artist name"
        />
      </div>

      {/* Description */}
      <div>
        <label className="text-xs font-semibold uppercase tracking-wider text-text-tertiary mb-1.5 block">Description</label>
        <textarea
          value={description}
          onChange={(e) => { setDescription(e.target.value); markDirty(); }}
          rows={4}
          className="w-full px-3 py-2 rounded-lg text-sm bg-bg-hover border border-border text-foreground outline-none focus:border-accent transition-colors resize-none"
          placeholder="Beat description..."
        />
      </div>

      {/* Tags */}
      <div>
        <label className="text-xs font-semibold uppercase tracking-wider text-text-tertiary mb-1.5 block">Tags</label>
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
          <button
            onClick={addTag}
            className="px-3 py-1.5 rounded-lg text-xs font-medium bg-bg-hover border border-border text-text-secondary hover:text-foreground transition-colors cursor-pointer"
          >
            <Plus size={12} />
          </button>
        </div>
      </div>

      {/* YouTube Link */}
      {beat.youtube && (
        <div className="p-3 rounded-lg" style={{ background: "var(--bg-hover)", border: "1px solid var(--border)" }}>
          <p className="text-xs font-semibold text-text-secondary mb-1">YouTube</p>
          <a
            href={beat.youtube.url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-sm text-accent hover:underline flex items-center gap-1"
          >
            {beat.youtube.title || beat.youtube.url}
          </a>
        </div>
      )}

      {/* Save Button */}
      <button
        onClick={save}
        disabled={!dirty || saving}
        className="w-full py-2.5 rounded-xl text-sm font-semibold flex items-center justify-center gap-2 transition-all duration-200 cursor-pointer"
        style={{
          background: dirty ? "linear-gradient(135deg, var(--accent), color-mix(in srgb, var(--accent) 70%, #8b5cf6))" : "var(--bg-hover)",
          color: dirty ? "#fff" : "var(--text-tertiary)",
          opacity: saving ? 0.6 : 1,
          boxShadow: dirty ? "0 4px 16px var(--accent-muted)" : "none",
        }}
      >
        {saving ? <Loader2 size={14} className="animate-spin" /> : saved ? <CheckCircle2 size={14} /> : <Save size={14} />}
        {saving ? "Saving..." : saved ? "Saved!" : "Save Changes"}
      </button>
    </div>
  );
}
