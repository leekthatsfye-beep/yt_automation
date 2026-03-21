"use client";

import { useState, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Youtube, Music, Film, Upload, X } from "lucide-react";

const STEPS = [
  {
    icon: Youtube,
    color: "#ff453a",
    title: "Connect YouTube",
    description: "Link your YouTube channel to enable direct uploads and scheduled publishing.",
  },
  {
    icon: Music,
    color: "#0a84ff",
    title: "Add Your Beats",
    description: "Drop audio files into the beats folder. We handle naming, metadata, and SEO.",
  },
  {
    icon: Film,
    color: "#30d158",
    title: "Render Videos",
    description: "One click renders professional videos with thumbnails for every beat.",
  },
  {
    icon: Upload,
    color: "#bf5af2",
    title: "Upload & Schedule",
    description: "Batch upload to YouTube with scheduling, privacy controls, and analytics.",
  },
];

const overlay = {
  hidden: { opacity: 0 },
  visible: { opacity: 1 },
  exit: { opacity: 0 },
};

const modal = {
  hidden: { opacity: 0, scale: 0.9, y: 20 },
  visible: {
    opacity: 1,
    scale: 1,
    y: 0,
    transition: { type: "spring" as const, damping: 25, stiffness: 300 },
  },
  exit: { opacity: 0, scale: 0.95, y: 10, transition: { duration: 0.2 } },
};

const stagger = {
  visible: { transition: { staggerChildren: 0.1, delayChildren: 0.2 } },
};

const stepItem = {
  hidden: { opacity: 0, x: -16 },
  visible: { opacity: 1, x: 0, transition: { duration: 0.4 } },
};

export default function OnboardingModal() {
  const [show, setShow] = useState(false);

  useEffect(() => {
    const seen = localStorage.getItem("fy3-onboarding-seen");
    if (!seen) setShow(true);
  }, []);

  const dismiss = () => {
    setShow(false);
    localStorage.setItem("fy3-onboarding-seen", "1");
  };

  return (
    <AnimatePresence>
      {show && (
        <motion.div
          className="fixed inset-0 z-[100] flex items-center justify-center p-4"
          variants={overlay}
          initial="hidden"
          animate="visible"
          exit="exit"
        >
          {/* Backdrop */}
          <motion.div
            className="absolute inset-0 bg-black/70"
            onClick={dismiss}
          />

          {/* Modal */}
          <motion.div
            className="relative w-full max-w-md rounded-lg p-8 bg-bg-card-solid border border-border shadow-[0_24px_64px_rgba(0,0,0,0.5)]"
            variants={modal}
          >
            {/* Close */}
            <button
              onClick={dismiss}
              className="absolute top-4 right-4 p-1.5 rounded-lg transition-colors text-text-tertiary hover:text-foreground"
            >
              <X size={18} />
            </button>

            {/* Header */}
            <div className="text-center mb-8">
              <div className="flex items-baseline justify-center gap-1 mb-2">
                <h2 className="text-2xl font-bold tracking-tight text-foreground">
                  Welcome to FY3
                </h2>
                <span className="text-lg font-bold text-accent">!</span>
              </div>
              <p className="text-sm text-text-tertiary">
                Your beat automation pipeline in 4 steps
              </p>
            </div>

            {/* Steps */}
            <motion.div className="space-y-4 mb-8" variants={stagger}>
              {STEPS.map((step, i) => {
                const Icon = step.icon;
                return (
                  <motion.div
                    key={step.title}
                    className="flex items-start gap-4 p-3 rounded-lg bg-muted"
                    variants={stepItem}
                  >
                    <div
                      className="w-10 h-10 rounded-lg flex items-center justify-center flex-shrink-0"
                      style={{ background: `${step.color}18` }}
                    >
                      <Icon size={18} style={{ color: step.color }} strokeWidth={1.8} />
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="text-[11px] font-bold tabular-nums w-5 h-5 rounded-md flex items-center justify-center bg-accent-muted text-accent">
                          {i + 1}
                        </span>
                        <h3 className="text-[13px] font-semibold text-foreground">
                          {step.title}
                        </h3>
                      </div>
                      <p className="text-[12px] mt-1 leading-relaxed text-text-tertiary">
                        {step.description}
                      </p>
                    </div>
                  </motion.div>
                );
              })}
            </motion.div>

            {/* CTA */}
            <button
              onClick={dismiss}
              className="w-full py-3 rounded-lg text-sm font-semibold transition-all duration-200 bg-primary text-white hover:brightness-110 cursor-pointer shadow-[0_0_15px_var(--accent-muted)]"
            >
              Get Started
            </button>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
