# NH Digital Future PAC — digitalfuturenh.com

A non-partisan New Hampshire political action committee supporting candidates who defend digital property, financial freedom, and the right to build the future.

## Stack

Static HTML/CSS/JS. No framework. Designed to be deployed by Nginx + git pull on the primary server.

## Layout

```
/                      site root
  index.html           Home
  about/index.html     About
  issues/index.html    Issues framework (six pillars)
  candidates/index.html  Endorsements
  news/index.html      News / statements
  involved/index.html  Donate, request endorsement, briefing list
  privacy/index.html
  terms/index.html
  css/style.css        Design system
  js/main.js           Nav, GA4, signup form, scroll/reveal
  images/              Hero photos, OG images, logo
  robots.txt
  sitemap.xml
  scripts/
    generate_images.py   gpt-image-1 hero/OG generator (no logos, no text)
    cloudflare_dns.sh    Upsert A records pointing to primary server
    deploy.sh            Push, pull on server, purge Cloudflare
    nginx.conf.example   Drop-in vhost
```

## Deploy

1. Cloudflare DNS → `./scripts/cloudflare_dns.sh`
2. Generate images (one-time) → `./scripts/generate_images.py`
3. Push to GitHub → `git push origin main`
4. On server: `git clone` to `/opt/nh-digital-future-pac`
5. Nginx vhost → see `scripts/nginx.conf.example`
6. Certbot → `sudo certbot --nginx -d digitalfuturenh.com -d www.digitalfuturenh.com`
7. Future updates → `./scripts/deploy.sh`

## Design rules (enforced)

- No emojis. No rounded corners. No template patterns.
- Clean white backgrounds. Dark navy sections with subtle cyan/violet gradient accents.
- Subtle circuit lines, pixel blocks, node patterns; geometric NH silhouette.
- Real NH photos for hero/break sections. Abstract blockchain grids OK; never Bitcoin/Ethereum logos.
- Cache-bust CSS/JS with `?v=N` and bump on deploy.

## Disclaimer

Paid for by NH Digital Future PAC. Not authorized by any candidate or candidate's committee. Contributions are not tax deductible.
