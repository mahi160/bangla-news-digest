// @ts-check
import { defineConfig } from 'astro/config';

import tailwindcss from '@tailwindcss/vite';

// https://astro.build/config
export default defineConfig({
  // Flat `runs/<name>.html` files, not `runs/<name>/index.html` -- matches
  // the manifest's `file` field and every relative link built against it
  // (feed.xml/opds.xml links, the run page's own "../index.html" back-link).
  build: {
    format: 'file'
  },
  vite: {
    plugins: [tailwindcss()]
  }
});