/**
 * Tailwind CSS — configuración del Motor Financiero.
 * Se compila a un archivo estático (static/css/app.css) para que la app
 * funcione 100% offline en la Raspberry Pi, sin depender de ningún CDN.
 *
 * Reconstruir tras editar plantillas:  npm run build:css
 */
module.exports = {
  darkMode: 'class',
  content: [
    './templates/**/*.html',
    './static/js/app.js',
    './static/js/charts.js',
    './static/js/forms.js',
    './static/js/theme.js',
  ],
  // Clases que se arman dinámicamente en Jinja (badge-{{ status|status_color }})
  // y por eso el scanner no las ve literalmente.
  safelist: [
    'badge-green', 'badge-red', 'badge-yellow',
    'badge-blue', 'badge-gray', 'badge-purple',
  ],
  theme: {
    extend: {
      colors: {
        primary: {
          50: '#eef2ff', 100: '#e0e7ff', 200: '#c7d2fe',
          300: '#a5b4fc', 400: '#818cf8', 500: '#6366f1',
          600: '#4f46e5', 700: '#4338ca', 800: '#3730a3',
          900: '#312e81', 950: '#1e1b4b',
        },
      },
      fontFamily: {
        sans: [
          'ui-sans-serif', 'system-ui', '-apple-system', 'BlinkMacSystemFont',
          'Segoe UI', 'Roboto', 'Helvetica Neue', 'Arial',
          'Apple Color Emoji', 'Segoe UI Emoji', 'Segoe UI Symbol', 'Noto Color Emoji',
          'sans-serif',
        ],
      },
      boxShadow: {
        soft: '0 1px 2px 0 rgb(15 23 42 / 0.04), 0 1px 3px 0 rgb(15 23 42 / 0.06)',
        card: '0 1px 3px rgb(15 23 42 / 0.06), 0 8px 24px -12px rgb(15 23 42 / 0.10)',
        lift: '0 10px 30px -10px rgb(15 23 42 / 0.18)',
      },
      borderRadius: {
        '2xl': '1rem',
        '3xl': '1.25rem',
      },
      keyframes: {
        'fade-in': {
          '0%': { opacity: '0', transform: 'translateY(8px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
      },
      animation: {
        'fade-in': 'fade-in 0.3s ease-out both',
      },
    },
  },
  plugins: [],
};
