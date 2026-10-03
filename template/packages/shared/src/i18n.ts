// Minimal i18n on the platform's own Intl: flat keys, `{name}` interpolation, and plurals as
// `key.one` / `key.other` (plus any category Intl.PluralRules returns for the locale).
// ponytail: no ICU select/ordinal support; switch to a library when a locale needs it.
//
// Hermes, the JavaScript engine of React Native and Expo, implements Intl.Collator, DateTimeFormat
// and NumberFormat but NOT Intl.PluralRules: `new Intl.PluralRules()` throws "undefined cannot be
// used as a constructor" at startup on a phone, while Node and the browser (where the tests and the
// web export run) have it. So it is used when it exists, and otherwise the rule for the locales this
// template ships (English, Spanish: `one` for exactly 1, else `other`). A locale with more plural
// categories (Arabic, Polish, Russian...) needs a polyfill or a library on native.

export type Messages = Record<string, string>;
type Params = Record<string, string | number>;

export function pluralSelector(locale: string): (count: number) => string {
  const rules = (Intl as { PluralRules?: typeof Intl.PluralRules }).PluralRules;
  if (rules) return (count) => new rules(locale).select(count);
  return (count) => (count === 1 ? 'one' : 'other');
}

export function createTranslator(messages: Messages, locale: string) {
  const plurals = { select: pluralSelector(locale) };
  return function t(key: string, params: Params = {}): string {
    let text = messages[key];
    if (typeof params.count === 'number') {
      text = messages[`${key}.${plurals.select(params.count)}`] ?? messages[`${key}.other`] ?? text;
    }
    if (text === undefined) return key; // visible in the UI and caught by the parity test
    return text.replace(/\{(\w+)\}/g, (match, name: string) =>
      name in params ? String(params[name]) : match,
    );
  };
}

/** Keys and `{placeholders}` that differ between the base locale and another (house rule I18N-1). */
export function localeDrift(base: Messages, other: Messages): string[] {
  const placeholders = (s: string) =>
    [...s.matchAll(/\{(\w+)\}/g)]
      .map((m) => m[1])
      .sort()
      .join(',');
  const problems: string[] = [];
  for (const key of Object.keys(base)) {
    if (!(key in other)) problems.push(`missing ${key}`);
    else if (placeholders(base[key]) !== placeholders(other[key]))
      problems.push(`placeholders differ in ${key}`);
  }
  for (const key of Object.keys(other)) if (!(key in base)) problems.push(`extra ${key}`);
  return problems;
}
