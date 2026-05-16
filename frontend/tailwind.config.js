/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Все цвета через CSS variables (см. src/index.css)
        bg: "var(--bg)",
        surface: "var(--surface)",
        "surface-2": "var(--surface-2)",
        border: "var(--border)",
        "border-hi": "var(--border-hi)",
        fg: "var(--fg)",
        muted: "var(--muted)",
        faint: "var(--faint)",
        accent: "var(--accent)",
        "accent-subtle": "var(--accent-subtle)",
        success: "var(--success)",
        "success-subtle": "var(--success-subtle)",
        warn: "var(--warn)",
        warning: "var(--warn)", // alias для существующих usage
        "warn-subtle": "var(--warn-subtle)",
        danger: "var(--danger)",
        "danger-subtle": "var(--danger-subtle)",
        error: "var(--danger)", // alias
      },
      fontFamily: {
        sans: ["Inter Variable", "Inter", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono Variable", "JetBrains Mono", "Menlo", "monospace"],
      },
      fontSize: {
        micro: ["11px", "14px"],
        tiny: ["12px", "16px"],
        h3: ["18px", "26px"],
        h2: ["24px", "32px"],
        h1: ["32px", "40px"],
      },
    },
  },
  plugins: [],
};
