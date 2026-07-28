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
        amber: {
          650: "#d4880a",
          600: "#e09413",
          550: "#e8a125",
          500: "#f0b03a",
        },
      },
    },
  },
  plugins: [],
};
