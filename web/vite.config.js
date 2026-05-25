import { defineConfig } from 'vite';

const isGitHubPages = process.env.GITHUB_PAGES === 'true';

export default defineConfig({
  // When deploying to GitHub Pages, set the correct base path.
  // For https://jchen3652.github.io/jetlag/  →  base must be '/jetlag/'
  base: isGitHubPages ? '/jetlag/' : '/',

  server: {
    port: 5173,
    open: true
  }
});
