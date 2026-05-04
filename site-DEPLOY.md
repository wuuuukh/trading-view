# Trading Report Website Deployment

This project now exports a static website into `site/`.

## Update The Website Files

Run:

```powershell
.\scripts\update_all.ps1
```

That command updates market data, regenerates reports, and copies the public website files into `site/`.

## Publish Options

### Cloudflare Pages

1. Create a new Pages project.
2. Upload the `site` folder directly.
3. Cloudflare will give you a public URL.

### Netlify

1. Go to Netlify Drop.
2. Drag the `site` folder onto the page.
3. Netlify will give you a public URL.

### GitHub Pages

1. Create a GitHub repository.
2. Upload the contents of `site`.
3. In repository settings, enable Pages from the main branch root.

## Public Entry

The website entry file is:

```text
site/index.html
```
