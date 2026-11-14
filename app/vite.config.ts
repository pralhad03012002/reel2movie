import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

// base './' keeps asset paths relative, like the manifest's start_url and scope.
export default defineConfig({ base: './', plugins: [react(), tailwindcss()] });
