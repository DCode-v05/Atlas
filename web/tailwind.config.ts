import type { Config } from "tailwindcss";

// Chrome palette is driven by CSS variables (index.css). Richer semantic
// palettes (departments / intents / sensitivity) live in src/theme.ts so the
// canvas graph and the DOM share one source of truth.
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
        gold: "var(--gold)",
        violet: "var(--violet)",
        coral: "var(--coral)",
        amber: "var(--amber)",
      },
      fontFamily: {
        display: ['"Syne"', "sans-serif"],
        sans: ['"Hanken Grotesk"', "system-ui", "sans-serif"],
        mono: ['"Spline Sans Mono"', "ui-monospace", "monospace"],
      },
    },
  },
  plugins: [],
} satisfies Config;
