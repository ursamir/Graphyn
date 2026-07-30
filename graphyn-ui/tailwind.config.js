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
        display: ['Syne', 'system-ui', 'sans-serif'],
        sans: ['"IBM Plex Sans"', 'system-ui', 'sans-serif'],
        mono: ['"IBM Plex Mono"', 'ui-monospace', 'monospace'],
      },
      backgroundImage: {
        mesh:
          'radial-gradient(ellipse at 10% 0%, rgba(30,181,166,0.18), transparent 45%), radial-gradient(ellipse at 90% 10%, rgba(70,91,111,0.16), transparent 40%), linear-gradient(180deg, #f4f6f8 0%, #e8eef2 100%)',
      },
    },
  },
  plugins: [],
}
