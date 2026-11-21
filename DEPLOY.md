# Deploy turkey alert live

## What you need first (nothing to install yet)

1. **eBird API key** - free at https://ebird.org/api/keygen (sign in, it generates instantly)
2. **Resend account + API key** - https://resend.com, then https://resend.com/api-keys
3. **Resend domain verified** - Resend > Domains > Add Domain > `danstaub.com`, then add the SPF and DKIM records it gives you at your DNS host. Until this is done, Resend can only email your own account address.

## Push the code

```bash
cd turkey-alert
git init
git add .
git commit -m "Turkey alert: per-town eBird alerts via Resend"
# create an empty repo on GitHub first, then:
git remote add origin https://github.com/danstaub/turkey-alert.git
git push -u origin main
```

`.gitignore` already excludes `.env` and `seen.json`. Never commit real keys.

## Host it (pick one)

### Railway (recommended, easiest)
1. https://railway.app > New Project > Deploy from GitHub repo > turkey-alert
2. Variables: `EBIRD_API_KEY`, `RESEND_API_KEY`, `FROM_EMAIL=dan@danstaub.com`, `APP_URL=https://alerts.danstaub.com`
3. Settings > Networking > Add custom domain > `alerts.danstaub.com`, then add the CNAME Railway gives you at your DNS host
4. Add a Cron service in the same project: `python3 turkey_alert.py`, schedule `*/30 * * * *`, same env vars

**Do NOT do step 4 as a separate service.** Railway gives each service its
own ephemeral filesystem and volumes cannot be shared between services,
so a separate cron service would find zero subscribers every run and
re-email the same sightings. The poller now runs inside `server.py`
itself, every 30 minutes, in the same container as the signup page.
Instead, add persistence to the web service:
- In Railway, click the turkey-alert service, three-dot menu > Add Volume,
  mount path `/data`, size 1 GB.
- Add two variables to that same service:
  `SUBSCRIBERS_FILE=/data/subscribers.json`
  `STATE_FILE=/data/seen.json`
  Without the volume, a redeploy wipes the subscriber list.

### Fly.io
1. `fly launch` (uses the Dockerfile), `fly secrets set EBIRD_API_KEY=... RESEND_API_KEY=... FROM_EMAIL=... APP_URL=...`
2. `fly certs add alerts.danstaub.com`, add the DNS records Fly gives you
3. Poller: `fly machine run` on a schedule, or a second app with a cron

### A VPS
1. Copy the files, `python3 server.py` behind nginx/Caddy, point `alerts.danstaub.com` at it
2. Cron: `*/30 * * * * cd /path/to/turkey-alert && /usr/bin/python3 turkey_alert.py >> turkey-alert.log 2>&1`

## Go-live checks

1. Visit https://alerts.danstaub.com, sign up with your own email, confirm you are in
2. `python3 turkey_alert.py --seed` once, so the Nov 17 sighting does not alert everyone on the first run
3. `python3 turkey_alert.py --test` to see the exact email
4. Wait for the next real turkey, or trigger a test send in Resend

## Notes

- Free tier math: Resend free is 3,000 emails/month, 100/day. Each sighting is one email per subscriber in that town.
- Subscribers live in `subscribers.json` on the server. Back it up before redeploys; a redeploy that wipes it loses the list.
- If the list ever grows, add a confirmation email before adding someone, so nobody can sign up someone else's address.
