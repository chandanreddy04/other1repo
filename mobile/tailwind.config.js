/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ['./app/**/*.{js,jsx,ts,tsx}', './components/**/*.{js,jsx,ts,tsx}'],
  theme: {
    extend: {
      colors: {
        primary: '#4A90E2',
        secondary: '#50C878',
        danger: '#E74C3C',
        warning: '#F39C12',
      },
    },
  },
  plugins: [],
}
