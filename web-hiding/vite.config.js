import { defineConfig } from 'vite';

const isGitHubPages = process.env.GITHUB_PAGES === 'true';

export default defineConfig({
  // Sibling fork of /web — deploy as /jetlag/hiding/ if needed later
  base: isGitHubPages ? '/jetlag/hiding/' : '/',
  server: {
    port: 5174,
    open: true
  }
});
