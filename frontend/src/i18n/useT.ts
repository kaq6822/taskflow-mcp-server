import { useStore } from '../store/store';
import { translations } from './translations';

export function useT() {
  const lang = useStore((s) => s.lang);
  return translations[lang];
}
