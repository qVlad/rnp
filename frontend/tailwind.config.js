/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: "#0b0d12",
        surface: "#13161d",
        border: "#262a35",
        muted: "#7d8492",
        accent: "#7c5cff",
        success: "#3ddc97",
        warn: "#ffb84d",
        danger: "#ff5c7a",
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "Menlo", "monospace"],
      },
    },
  },
  plugins: [],
};
