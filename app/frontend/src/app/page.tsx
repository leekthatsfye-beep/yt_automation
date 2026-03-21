"use client";

import { useRef } from "react";
import Link from "next/link";
import { motion, useInView } from "framer-motion";
import {
  Film,
  Upload,
  Calendar,
  Search,
  Sparkles,
  BarChart3,
  Music,
  ArrowRight,
  Zap,
  Play,
} from "lucide-react";
import { Button } from "@/components/ui/button";

/* ── animation helpers ─────────────────────────────────────────────── */

const fadeUp = {
  hidden: { opacity: 0, y: 30 },
  visible: {
    opacity: 1,
    y: 0,
    transition: { duration: 0.6, ease: [0.25, 0.46, 0.45, 0.94] as const },
  },
};

const stagger = {
  hidden: {},
  visible: { transition: { staggerChildren: 0.12 } },
};

function Section({
  children,
  className = "",
}: {
  children: React.ReactNode;
  className?: string;
}) {
  const ref = useRef(null);
  const inView = useInView(ref, { once: true, margin: "-80px" });
  return (
    <motion.section
      ref={ref}
      initial="hidden"
      animate={inView ? "visible" : "hidden"}
      variants={stagger}
      className={className}
    >
      {children}
    </motion.section>
  );
}

/* ── data ──────────────────────────────────────────────────────────── */

const FEATURES = [
  {
    icon: Film,
    title: "Video Rendering",
    desc: "One-click rendering with zoom effects, custom backgrounds, and branded overlays.",
    color: "#30d158",
  },
  {
    icon: Upload,
    title: "YouTube Upload",
    desc: "Batch upload to YouTube with privacy controls and metadata.",
    color: "#ff453a",
  },
  {
    icon: Calendar,
    title: "Scheduling",
    desc: "Queue videos for timed release across days or weeks.",
    color: "#ffd60a",
  },
  {
    icon: Search,
    title: "SEO Optimization",
    desc: "Auto-generate titles, tags, and descriptions for discovery.",
    color: "#0a84ff",
  },
  {
    icon: Sparkles,
    title: "AI Studio",
    desc: "Generate beats with AI using genre presets and custom prompts.",
    color: "#bf5af2",
  },
  {
    icon: BarChart3,
    title: "Analytics",
    desc: "Track your pipeline progress, upload history, and performance.",
    color: "#ff9f0a",
  },
];

const STEPS = [
  {
    num: "01",
    icon: Music,
    title: "Drop Your Beats",
    desc: "Add MP3 or WAV files to your library with drag-and-drop.",
    color: "#0a84ff",
  },
  {
    num: "02",
    icon: Zap,
    title: "Render & Optimize",
    desc: "Auto-generate videos, thumbnails, and SEO metadata in one click.",
    color: "#30d158",
  },
  {
    num: "03",
    icon: Upload,
    title: "Upload & Schedule",
    desc: "Batch upload to YouTube on your timeline with scheduling.",
    color: "#ff9f0a",
  },
];

/* ── page ──────────────────────────────────────────────────────────── */

export default function LandingPage() {
  return (
    <div className="bg-background">
      {/* ── Navbar ──────────────────────────────────────────────── */}
      <nav
        className="fixed top-0 left-0 right-0 z-50 flex items-center justify-between px-6 md:px-10 py-4 border-b border-border"
        style={{
          background: "rgba(0, 0, 0, 0.6)",
        }}
      >
        <div className="flex items-baseline gap-1">
          <span className="text-xl font-bold text-foreground">
            FY3
          </span>
          <span className="text-xs font-bold text-accent">
            !
          </span>
        </div>
        <div className="flex items-center gap-3">
          <Link
            href="/dashboard"
            className="text-sm font-medium hidden sm:block text-muted-foreground"
          >
            Dashboard
          </Link>
          <Button asChild>
            <Link href="/dashboard" prefetch={false}>
              Get Started
            </Link>
          </Button>
        </div>
      </nav>

      {/* ── Hero ────────────────────────────────────────────────── */}
      <section
        className="relative flex flex-col items-center justify-center text-center min-h-screen px-6 pt-20"
      >
        {/* Background glow */}
        <div
          className="absolute pointer-events-none w-[700px] h-[700px] rounded-full top-[15%] left-1/2 -translate-x-1/2 blur-[100px]"
          style={{
            background:
              "radial-gradient(circle, var(--accent-muted) 0%, transparent 70%)",
          }}
        />

        <motion.div
          initial="hidden"
          animate="visible"
          variants={stagger}
          className="relative z-10"
        >
          <motion.h1
            variants={fadeUp}
            className="text-4xl sm:text-5xl md:text-7xl font-bold tracking-tight mb-6 text-foreground"
            style={{ lineHeight: 1.1 }}
          >
            Automate Your
            <br />
            <span className="text-accent">Beat Empire</span>
          </motion.h1>
          <motion.p
            variants={fadeUp}
            className="text-base sm:text-lg md:text-xl max-w-2xl mx-auto mb-10 text-muted-foreground"
            style={{ lineHeight: 1.7 }}
          >
            Render videos, generate thumbnails, optimize SEO, and upload to
            YouTube — all from one command center.
          </motion.p>
          <motion.div
            variants={fadeUp}
            className="flex flex-col sm:flex-row items-center justify-center gap-4"
          >
            <Button asChild size="lg" className="px-8 py-3.5 h-auto rounded-lg text-base font-semibold">
              <Link href="/dashboard" prefetch={false}>
                Start Automating <ArrowRight size={18} />
              </Link>
            </Button>
            <Button asChild variant="glass" size="lg" className="px-8 py-3.5 h-auto rounded-lg text-base font-semibold">
              <Link href="/beats" prefetch={false}>
                <Play size={16} /> Beat Library
              </Link>
            </Button>
          </motion.div>
        </motion.div>
      </section>

      {/* ── Features ────────────────────────────────────────────── */}
      <Section className="max-w-6xl mx-auto px-6 py-24">
        <motion.div variants={fadeUp} className="text-center mb-16">
          <h2 className="text-3xl md:text-4xl font-bold tracking-tight mb-4 text-foreground">
            Everything You Need
          </h2>
          <p className="text-base max-w-xl mx-auto text-muted-foreground">
            From beat to YouTube video in minutes, not hours.
          </p>
        </motion.div>

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-5">
          {FEATURES.map((f) => (
            <motion.div
              key={f.title}
              variants={fadeUp}
              className="bg-bg-card border border-border rounded-lg p-6 cursor-default"
            >
              <div
                className="w-11 h-11 rounded-lg flex items-center justify-center mb-4"
                style={{ background: `${f.color}18` }}
              >
                <f.icon size={20} style={{ color: f.color }} />
              </div>
              <h3 className="text-[15px] font-semibold mb-1.5 text-foreground">
                {f.title}
              </h3>
              <p className="text-[13px] leading-relaxed text-text-tertiary">
                {f.desc}
              </p>
            </motion.div>
          ))}
        </div>
      </Section>

      {/* ── How It Works ────────────────────────────────────────── */}
      <Section className="max-w-4xl mx-auto px-6 py-24">
        <motion.div variants={fadeUp} className="text-center mb-16">
          <h2 className="text-3xl md:text-4xl font-bold tracking-tight mb-4 text-foreground">
            How It Works
          </h2>
          <p className="text-base max-w-lg mx-auto text-muted-foreground">
            Three steps from beat file to published YouTube video.
          </p>
        </motion.div>

        <div className="relative">
          {/* Connecting line */}
          <div className="absolute left-6 top-8 bottom-8 w-px hidden md:block bg-border" />

          <div className="space-y-8">
            {STEPS.map((s) => (
              <motion.div
                key={s.num}
                variants={fadeUp}
                className="flex gap-6 items-start"
              >
                <div
                  className="relative z-10 w-12 h-12 rounded-lg flex items-center justify-center flex-shrink-0"
                  style={{
                    background: `${s.color}18`,
                    border: `1px solid ${s.color}30`,
                  }}
                >
                  <s.icon size={20} style={{ color: s.color }} />
                </div>
                <div className="flex-1 pt-1">
                  <div className="flex items-center gap-3 mb-1.5">
                    <span
                      className="text-[11px] font-bold tracking-widest"
                      style={{ color: s.color }}
                    >
                      STEP {s.num}
                    </span>
                  </div>
                  <h3 className="text-lg font-semibold mb-1 text-foreground">
                    {s.title}
                  </h3>
                  <p className="text-[14px] text-text-tertiary">
                    {s.desc}
                  </p>
                </div>
              </motion.div>
            ))}
          </div>
        </div>
      </Section>

      {/* ── CTA Footer ──────────────────────────────────────────── */}
      <Section className="max-w-4xl mx-auto px-6 pb-24">
        <motion.div
          variants={fadeUp}
          className="bg-bg-card border border-border rounded-lg text-center p-10 md:p-16"
        >
          <h2 className="text-2xl md:text-3xl font-bold tracking-tight mb-4 text-foreground">
            Ready to automate your workflow?
          </h2>
          <p className="text-[15px] max-w-md mx-auto mb-8 text-muted-foreground">
            Stop spending hours on video rendering and uploads. Let FY3 handle
            the pipeline so you can focus on making beats.
          </p>
          <Button asChild size="lg" className="px-10 py-4 h-auto rounded-lg text-base font-semibold">
            <Link href="/dashboard" prefetch={false}>
              Get Started Free <ArrowRight size={18} />
            </Link>
          </Button>
        </motion.div>
      </Section>

      {/* ── Footer ──────────────────────────────────────────────── */}
      <footer className="max-w-6xl mx-auto px-6 py-8 flex items-center justify-between">
        <div className="flex items-baseline gap-1">
          <span className="text-sm font-bold text-text-tertiary">
            FY3
          </span>
          <span className="text-[9px] font-bold text-accent">
            !
          </span>
        </div>
        <p className="text-[12px] text-text-tertiary">
          Automation Center
        </p>
      </footer>
    </div>
  );
}
