import type { Metadata, Viewport } from "next";
import { GeistSans } from "geist/font/sans";
import { GeistMono } from "geist/font/mono";
import "./globals.css";
import ClientShell from "@/components/ClientShell";

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  maximumScale: 1,
  userScalable: false,
};

export const metadata: Metadata = {
  title: "FY3 Automation Center",
  description: "YouTube beat automation pipeline",
  manifest: "/manifest.json",
  appleWebApp: {
    capable: true,
    statusBarStyle: "black-translucent",
    title: "FY3!",
  },
  icons: {
    icon: "/icon-192.png",
    apple: "/apple-touch-icon.png",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" data-theme="midnight" suppressHydrationWarning>
      <head>
        <meta name="theme-color" content="#0a84ff" />
        {/* Prevent iOS PWA aggressive caching */}
        <meta httpEquiv="Cache-Control" content="no-cache, no-store, must-revalidate" />
        <meta httpEquiv="Pragma" content="no-cache" />
        <meta httpEquiv="Expires" content="0" />
        {/* Error recovery — smart retry with max 3 attempts, cooldown, grace period */}
        <script
          dangerouslySetInnerHTML={{
            __html: `
              (function() {
                var KEY = 'fy3-chunk-reload';
                var COUNT_KEY = 'fy3-reload-count';
                var COOLDOWN = 10000;
                var MAX_RETRIES = 3;
                var pageStart = Date.now();

                function isRecoverableError(msg) {
                  msg = (msg || '').toLowerCase();
                  return (
                    msg.includes('loading chunk') ||
                    msg.includes('loading css chunk') ||
                    msg.includes('failed to fetch') ||
                    msg.includes('dynamically imported module') ||
                    msg.includes("unexpected token '<'") ||
                    msg.includes('not valid javascript') ||
                    msg.includes('load failed') ||
                    msg.includes('mime type')
                  );
                }

                function tryRecover() {
                  try {
                    // Grace period: skip errors in first 3s (server may still be compiling)
                    if (Date.now() - pageStart < 3000) return;
                    // Max retries guard
                    var count = parseInt(sessionStorage.getItem(COUNT_KEY) || '0');
                    if (count >= MAX_RETRIES) return;
                    // Cooldown guard
                    var last = sessionStorage.getItem(KEY);
                    var now = Date.now();
                    if (last && now - parseInt(last) < COOLDOWN) return;
                    sessionStorage.setItem(KEY, String(now));
                    sessionStorage.setItem(COUNT_KEY, String(count + 1));
                    // Clear caches before reload
                    if (window.caches) {
                      caches.keys().then(function(names) {
                        return Promise.all(names.map(function(n) { return caches.delete(n); }));
                      }).then(function() { window.location.reload(); }).catch(function() { window.location.reload(); });
                    } else {
                      window.location.reload();
                    }
                  } catch(e) {
                    window.location.reload();
                  }
                }

                // Layer 1: Catch JS errors — only specific chunk/module errors
                window.addEventListener('error', function(e) {
                  if (e.message && isRecoverableError(e.message)) tryRecover();
                }, true);

                // Layer 2: Catch async errors (dynamic imports, fetch failures)
                window.addEventListener('unhandledrejection', function(e) {
                  var msg = '';
                  if (e.reason) msg = e.reason.message || e.reason.toString() || '';
                  if (isRecoverableError(msg)) tryRecover();
                });

                // Layer 3: Detect "Internal Server Error" text or blank screen — retry
                setTimeout(function() {
                  try {
                    var body = document.body;
                    if (!body) return;
                    var text = (body.innerText || '').trim();
                    var main = document.querySelector('main');
                    var isServerError = text === 'Internal Server Error';
                    var isBlank = !main && body.children.length < 2;
                    if (isServerError || isBlank) {
                      var last = sessionStorage.getItem('fy3-blank-recovery');
                      var now = Date.now();
                      if (!last || now - parseInt(last) > 15000) {
                        sessionStorage.setItem('fy3-blank-recovery', String(now));
                        window.location.reload();
                      }
                    }
                  } catch(e) {}
                }, 5000);

                // Layer 4: On successful load, reset retry counter
                window.addEventListener('load', function() {
                  setTimeout(function() {
                    try {
                      sessionStorage.removeItem(KEY);
                      sessionStorage.removeItem(COUNT_KEY);
                    } catch(e) {}
                  }, 5000);
                });
              })();
            `,
          }}
        />
      </head>
      <body className={`${GeistSans.variable} ${GeistMono.variable} antialiased`}>
        <ClientShell>{children}</ClientShell>
      </body>
    </html>
  );
}
