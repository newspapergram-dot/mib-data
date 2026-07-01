import { defineConfig } from 'astro/config';
import tailwind from '@astrojs/tailwind';

export default defineConfig({
  integrations: [tailwind()],
  output: 'static', // build puramente statica ad ogni push su main (GitOps/Jamstack)
});
