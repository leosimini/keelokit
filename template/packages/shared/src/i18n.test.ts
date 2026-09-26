import { describe, expect, it } from 'vitest';
import { createTranslator, localeDrift } from './i18n.js';

describe('createTranslator', () => {
  const t = createTranslator(
    {
      hello: 'Hola {name}',
      'seats.one': 'Queda {count} lugar',
      'seats.other': 'Quedan {count} lugares',
    },
    'es-AR',
  );

  it('interpolates params', () => expect(t('hello', { name: 'Ana' })).toBe('Hola Ana'));
  it('picks the plural form', () => {
    expect(t('seats', { count: 1 })).toBe('Queda 1 lugar');
    expect(t('seats', { count: 3 })).toBe('Quedan 3 lugares');
  });
  it('shows the key when a translation is missing', () => expect(t('nope')).toBe('nope'));
});

describe('localeDrift', () => {
  it('reports missing, extra and placeholder differences', () => {
    expect(localeDrift({ a: 'x {n}', b: 'y' }, { a: 'x', c: 'z' })).toEqual([
      'placeholders differ in a',
      'missing b',
      'extra c',
    ]);
  });
});
