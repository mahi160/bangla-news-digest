// @ts-check
import { defineConfig } from 'astro/config';

import tailwindcss from '@tailwindcss/vite';

// https://astro.build/config
export default defineConfig({
  // GitHub Pages *project* page (repo name subpath), not a user/org root
  // page -- without `base`, Astro emits root-absolute asset URLs like
  // `/_astro/Layout.css` that 404 once actually served under the subpath.
  site: 'https://mahi160.github.io',
  base: '/bangla-news-digest',
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