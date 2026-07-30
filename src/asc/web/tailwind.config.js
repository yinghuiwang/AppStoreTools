/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ["./src/asc/web/templates/**/*.html"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["DM Sans", "system-ui", "sans-serif"],
        mono: ["Fira Code", "monospace"],
        display: ["Instrument Serif", "serif"],
      },
      colors: {
        obsidian: {
          950: "#0a0a0c",
          900: "#111115",
          850: "#16161b",
          800: "#1c1c23",
          700: "#27272f",
          600: "#35353f",
          500: "#4a4a56",
          400: "#6b6b78",
          300: "#91919e",
          200: "#b8b8c3",
          100: "#dddde3",
          50: "#f0f0f4",
        },
        // Named amber historically; values are the mint / signal-lime accent scale.
        amber: {
          650: "#147d72",
          600: "#199c89",
          550: "#23c9a8",
          500: "#8ff5d2",
          400: "#b9ef5b",
          300: "#e4ffd0",
        },
      },
    },
  },
  plugins: [],
};
