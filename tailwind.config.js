/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./app/templates/**/*.html",
    "./app/static/**/*.js",
  ],
  theme: {
    extend: {
      colors: {
        dark: {
          900: '#0a0e1a',
          800: '#111827',
          700: '#1a2035',
          600: '#232b3e',
          500: '#2d3650',
        },
        accent: {
          green: '#22c55e',
          red: '#ef4444',
          blue: '#3b82f6',
          yellow: '#eab308',
        },
      },
    },
  },
  plugins: [],
}
