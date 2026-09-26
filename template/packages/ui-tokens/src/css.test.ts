import { expect, it } from 'vitest';
import { colors, cssVariables } from './index.js';

it('exposes tokens as CSS custom properties', () => {
  const vars = cssVariables();
  expect(vars['--color-text-muted']).toBe(colors.textMuted);
  expect(vars['--spacing-md']).toBe('16px');
  expect(vars['--font-size-lg']).toBe('20px');
});
