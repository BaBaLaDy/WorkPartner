export type Locale = 'zh' | 'en';

export function pick(locale: Locale, zh: string, en: string) {
  return locale === 'zh' ? zh : en;
}

export function localeTag(locale: Locale) {
  return locale === 'zh' ? 'zh-CN' : 'en-US';
}

export function inferInitialLocale(): Locale {
  if (typeof window === 'undefined') return 'zh';
  const saved = localStorage.getItem('locale');
  if (saved === 'zh' || saved === 'en') return saved;
  return navigator.language.toLowerCase().startsWith('zh') ? 'zh' : 'en';
}
