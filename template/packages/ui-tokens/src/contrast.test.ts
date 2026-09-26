// Enforces house rule A11Y-1: every text/background pair the apps use meets WCAG AA (4.5:1).
import { describe, expect, it } from 'vitest';
import { colors, contrastRatio } from './index.js';

const pairs: [keyof typeof colors, keyof typeof colors][] = [
  ['text', 'background'],
  ['text', 'surface'],
  ['textMuted', 'background'],
  ['onPrimary', 'primary'],
  ['danger', 'background'],
];

describe('token contrast', () => {
  it.each(pairs)('%s on %s is at least 4.5:1', (fg, bg) => {
    expect(contrastRatio(colors[fg], colors[bg])).toBeGreaterThanOrEqual(4.5);
  });

  it('computes the known black/white ratio', () => {
    expect(contrastRatio('#000000', '#FFFFFF')).toBeCloseTo(21, 5);
  });
});
