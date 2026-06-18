import type { Config } from "tailwindcss";

// Chrome palette is driven by CSS variables (index.css). Richer semantic
// palettes (departments / intents / sensitivity) live in src/theme.ts so the
// canvas graph and the DOM share one source of truth. Token names are kept
// stable across redesigns so className references never break.
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        base: "var(--bg)",
        void: "var(--void)",
        surface: "var(--surface)",
        panel: "var(--panel)",
        "panel-solid": "var(--panel-solid)",
        edge: "var(--border)",
        "edge-bright": "var(--border-bright)",
        ink: "var(--text)",
        ink2: "var(--text-2)",
        muted: "var(--muted)",
        faint: "var(--faint)",
        accent: "var(--accent)",
        "accent-bright": "var(--accent-bright)",
        cyan: "var(--cyan)",
        gold: "var(--gold)",
        violet: "var(--violet)",
        coral: "var(--coral)",
        amber: "var(--amber)",
        red: "var(--red)",
        ok: "var(--ok)",
      },
      fontFamily: {
        display: ['"Fraunces"', "Georgia", "serif"],
        sans: ['"Public Sans"', "system-ui", "sans-serif"],
        mono: ['"JetBrains Mono"', "ui-monospace", "monospace"],
      },
    },
  },
  plugins: [],
} satisfies Config;
