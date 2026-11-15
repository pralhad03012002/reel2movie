import { defineConfig, type Plugin } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';
import { copyFileSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const here = (p: string) => fileURLToPath(new URL(p, import.meta.url));
const DEV_MATCH = 'http://127.0.0.1/*'; // stands in for an OTT site in browser tests; only with RP_DEV=1

// Copies manifest.json (adding the dev match when RP_DEV=1) and the icons into dist.
const copyStatic = (): Plugin => ({
  name: 'copy-static',
  closeBundle() {
    const m = JSON.parse(readFileSync(here('manifest.json'), 'utf8'));
    if (process.env.RP_DEV === '1') {
      m.content_scripts[0].matches.push(DEV_MATCH);
      m.web_accessible_resources[0].matches.push(DEV_MATCH);
    }
    mkdirSync(here('dist'), { recursive: true });
    writeFileSync(here('dist/manifest.json'), JSON.stringify(m, null, 2));
    for (const f of ['icon-192.png', 'icon-512.png']) copyFileSync(here(`public/${f}`), here(`dist/${f}`));
  },
});

// Three passes (a single Vite build cannot mix an ES service worker, an IIFE content script and HTML pages):
//   pages (default first run) -> overlay.html, connect.html; background -> background.js (ES); content -> content.js (IIFE).
export default defineConfig(({ mode }) => {
  const lib = (entry: string, format: 'es' | 'iife', name: string) => ({
    emptyOutDir: false,
    lib: { entry: here(entry), formats: [format], name: 'rpContent', fileName: () => name },
  });
  return {
    base: './',
    publicDir: false,
    // one copy of React & co: shared components in ../app would otherwise resolve their own from app/node_modules
    resolve: { alias: { '@app': here('../app/src') }, dedupe: ['react', 'react-dom', 'framer-motion', 'lucide-react'] },
    define: { __RP_DEV__: JSON.stringify(process.env.RP_DEV === '1') }, // dev-only test hooks; false (and tree-shaken) in the normal build
    plugins: mode === 'pages' ? [react(), tailwindcss(), copyStatic()] : [],
    build: {
      outDir: here('dist'),
      target: 'es2022',
      ...(mode === 'background' ? lib('src/background.ts', 'es', 'background.js') : {}),
      ...(mode === 'content' ? lib('src/content/main.ts', 'iife', 'content.js') : {}),
      ...(mode === 'pages' ? { emptyOutDir: true, rollupOptions: { input: { overlay: here('overlay.html'), connect: here('connect.html') } } } : {}),
    },
  };
});
