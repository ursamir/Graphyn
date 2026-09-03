/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        ink: {
          50: '#f4f6f8',
          100: '#e4e9ee',
          200: '#c9d3dc',
          300: '#a3b3c2',
          400: '#768ea3',
          500: '#5a7288',
          600: '#465b6f',
          700: '#3a4b5b',
          800: '#323f4c',
          900: '#2c3641',
          950: '#1a2129',
        },
        accent: {
          50: '#edfdfa',
          100: '#d2faf3',
          200: '#a9f3e7',
          300: '#71e6d6',
          400: '#38d0bf',
          500: '#1eb5a6',
          600: '#159288',
          700: '#15746e',
          800: '#165d59',
          900: '#174d4a',
        },
      },
      fontFamily: {
        display: ['Inter', 'system-ui', 'sans-serif'],
        sans: ['Inter', 'system-ui', 'sans-serif'],
        mono: ['"IBM Plex Mono"', 'ui-monospace', 'monospace'],
      },
      boxShadow: {
        soft: '0 8px 24px rgba(26, 33, 41, 0.08), 0 1px 2px rgba(26, 33, 41, 0.04)',
      },
      backgroundImage: {
        mesh:
          'radial-gradient(ellipse at 10% 0%, rgba(30,181,166,0.14), transparent 45%), radial-gradient(ellipse at 90% 10%, rgba(70,91,111,0.12), transparent 40%), linear-gradient(180deg, #eef2f6 0%, #e4ebf1 100%)',
      },
    },
  },
  plugins: [],
}
