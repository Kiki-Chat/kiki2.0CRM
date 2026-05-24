/** @type {import('tailwindcss').Config} */
export default {
  darkMode: ['selector', '[data-theme="dark"]'],
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        // Surfaces & neutrals (semantic — swap per theme via CSS vars)
        bg: 'var(--bg)',
        sidebar: 'var(--sidebar)',
        surface: 'var(--surface)',
        alt: 'var(--surface-alt)',
        border: 'var(--border)',
        'border-faint': 'var(--border-faint)',
        text: 'var(--text)',
        body: 'var(--body)',
        muted: 'var(--muted)',
        faint: 'var(--faint)',
        // Brand greens
        'green-brand': 'var(--green-brand)',
        'green-primary': 'var(--green-primary)',
        'green-deep': 'var(--green-deep)',
        'green-tint-50': 'var(--green-tint-50)',
        'green-tint-100': 'var(--green-tint-100)',
        'green-tint-200': 'var(--green-tint-200)',
        // Functional semantic
        success: 'var(--success)',
        'success-bg': 'var(--success-bg)',
        warning: 'var(--warning)',
        'warning-bg': 'var(--warning-bg)',
        error: 'var(--error)',
        'error-bg': 'var(--error-bg)',
        info: 'var(--info)',
        'info-bg': 'var(--info-bg)',
        ai: 'var(--ai)',
        'ai-bg': 'var(--ai-bg)',
      },
      fontFamily: {
        heading: ['Söhne', 'Inter', 'system-ui', 'sans-serif'],
        sans: ['Inter', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'ui-monospace', 'monospace'],
      },
      fontSize: {
        xs: ['12px', '16px'],
        sm: ['14px', '20px'],
        base: ['15px', '24px'],
        md: ['17px', '26px'],
        lg: ['20px', '28px'],
        xl: ['24px', '32px'],
        '2xl': ['30px', '38px'],
        '3xl': ['36px', '44px'],
      },
      borderRadius: {
        sm: '4px',
        md: '8px',
        lg: '12px',
        xl: '16px',
      },
      boxShadow: {
        e1: 'var(--elevation-1)',
        e2: 'var(--elevation-2)',
        e3: 'var(--elevation-3)',
      },
    },
  },
  plugins: [],
}
