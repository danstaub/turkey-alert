# Turkey alert: Roswell, GA

A little public app: anyone leaves their email, and they get an email when a Wild Turkey is reported on eBird within 25 miles of Roswell, GA.

## Files

- `server.py` - signup page (stdlib only, no dependencies). Serves the form, stores emails in `subscribers.json`, handles unsubscribe links.
- `turkey_alert.py` - the poller. Checks eBird, dedupes by checklist ID in `seen.json`, emails every subscriber via Resend.
- `subscribers.json` - the email list. One entry per person, with signup date.
- `.env.example` - copy to `.env` and fill in.

## How it works

- eBird: `GET /v2/data/obs/geo/recent/wiltur` at Roswell (34.0232, -84.3616), 25-mile (40 km) radius, last 7 days
- Email: Resend `POST https://api.resend.com/emails`, one call per subscriber, unsubscribe link in every email
- Cost: $0 on Resend's free tier, 3,000 emails/month, 100/day. Each sighting costs one email per subscriber, so 20 subscribers and 1 sighting is 20 emails. Turkeys near Roswell are rare, so this stays well inside free.

## Setup: alerts.danstaub.com

1. **Resend domain:** in Resend, Domains > Add Domain, enter `danstaub.com`. Add the SPF and DKIM records Resend gives you at your DNS host. That is what lets you email strangers, the test sender `onboarding@resend.dev` can only email your own account address.
2. **Keys:** eBird API key, free at https://ebird.org/api/keygen. Resend API key at https://resend.com/api-keys.
3. **Config:** copy `.env.example` to `.env`, set `EBIRD_API_KEY`, `RESEND_API_KEY`, `FROM_EMAIL=dan@danstaub.com`, `APP_URL=https://alerts.danstaub.com`.
4. **Host it:** this needs a server that stays up, a $5 VPS, Railway, or Fly.io all work. Point `alerts.danstaub.com` at it, run `python3 server.py`, and schedule the poller every 30 minutes:
   ```
   */30 * * * * cd /path/to/turkey-alert && /usr/bin/python3 turkey_alert.py >> turkey-alert.log 2>&1
   ```

## Run locally

```bash
python3 server.py                 # signup page on http://localhost:8000
python3 turkey_alert.py --seed    # first run only: mark current sightings seen, send nothing
python3 turkey_alert.py           # check once, email subscribers on new sightings
python3 turkey_alert.py --dry-run # show who would be emailed, send nothing
```

## Notes

- Baseline: the last Fulton County Wild Turkey on eBird was Nov 17, 2026, by Robert Massie. Run `--seed` first or that sighting will alert everyone on the first run (it is still inside the 7-day window).
- eBird's `back` parameter caps at 30 days, and the geo endpoint caps radius at 50 km.
- This is single opt-in on purpose for a tiny fun list. If it ever grows, add a confirmation email before adding someone, so nobody can sign up someone else's address.
