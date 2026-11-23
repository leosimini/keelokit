// The single source of design tokens. Web, mobile and site import these values; none of them
// hard-codes a colour. Change the brand here and every app follows.

export const colors = {
  background: '#FFFFFF',
  surface: '#F4F5F7',
  text: '#0B0F19',
  textMuted: '#4B5563',
  primary: '#15803D',
  onPrimary: '#FFFFFF',
  danger: '#B91C1C',
  border: '#E5E7EB',
} as const;

export const spacing = { xs: 4, sm: 8, md: 16, lg: 24, xl: 32 } as const;
export const radius = { sm: 6, md: 10, lg: 16 } as const;
export const font = {
  family: 'system-ui, -apple-system, "Segoe UI", Roboto, sans-serif',
  size: { sm: 14, md: 16, lg: 20, xl: 28 },
} as const;

/** WCAG 2.x contrast ratio between two #RRGGBB colours. */
export function contrastRatio(a: string, b: string): number {
  const luminance = (hex: string) => {
    const [r, g, bl] = [1, 3, 5].map((i) => {
      const c = parseInt(hex.slice(i, i + 2), 16) / 255;
      return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
    });
    return 0.2126 * r + 0.7152 * g + 0.0722 * bl;
  };
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

const kebab = (key: string) => key.replace(/[A-Z]/g, (c) => `-${c.toLowerCase()}`);

/** Tokens as CSS custom properties for web and site: colors.textMuted → --color-text-muted, numbers → px. */
export function cssVariables(): Record<string, string> {
  const vars: Record<string, string> = {};
  const walk = (name: string, value: unknown) => {
    if (typeof value === 'object' && value !== null) {
      for (const [key, child] of Object.entries(value)) walk(`${name}-${kebab(key)}`, child);
    } else {
      vars[name] = typeof value === 'number' ? `${value}px` : String(value);
    }
  };
  walk('--color', colors);
  walk('--spacing', spacing);
  walk('--radius', radius);
  walk('--font', font);
  return vars;
}
