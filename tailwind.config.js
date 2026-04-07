/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./app/templates/**/*.html",
    "./app/static/**/*.js",
  ],
  theme: {
    extend: {
      colors: {
        // Linear design palette
        dark: {
          900: '#08090a',   // page background
          800: '#0f1011',   // panel / sidebar
          700: '#191a1b',   // surface / card
          600: '#28282c',   // hover state
          500: '#34343a',   // border solid
        },
        accent: {
          green:  '#10b981',  // success / positive P&L
          red:    '#f87171',  // danger / negative P&L
          blue:   '#7170ff',  // Linear indigo accent (active / links)
          yellow: '#facc15',  // warning
          indigo: '#5e6ad2',  // CTA button background
        },
      },
    },
  },
  plugins: [],
}
