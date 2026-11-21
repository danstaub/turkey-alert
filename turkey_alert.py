#!/usr/bin/env python3
"""
Turkey alert - per-town version

Anyone can sign up at the signup page (server.py), pick a town, and get
emailed when a Wild Turkey is reported near that town. Not just Roswell.

How it works
------------
1. Signup: server.py stores each subscriber with a town, lat, lng,
   dist_km (40 km = 25 miles) in subscribers.json.
2. Poll: this script groups subscribers by location, then checks eBird
   once per unique location:
   GET /v2/data/obs/geo/recent/wiltur?lat=..&lng=..&dist=40&back=7
   Auth: x-ebirdapitoken header. Free key: https://ebird.org/api/keygen
3. Dedupe: seen checklist IDs are stored in seen.json, keyed by
   location + checklist ID, so a sighting alerts once per town.
4. Email: POST https://api.resend.com/emails, one call per subscriber.
   Resend free tier: 3,000 emails/month, 100/day, no card.
   Each sighting costs one email per subscriber in that town.
   FROM must be on a verified domain in Resend: danstaub.com.

Run it
-------
  cp .env.example .env   # fill in keys, FROM_EMAIL, APP_URL
  python3 server.py                 # signup page on http://localhost:8000
  python3 turkey_alert.py --seed    # first run: mark current sightings seen, send nothing
  python3 turkey_alert.py           # check once, email subscribers on new sightings
  python3 turkey_alert.py --dry-run # show who would be emailed, send nothing

Schedule the poller every 30 min (eBird checklists lag ~1 hr):
  */30 * * * * cd /path/to/turkey-alert && /usr/bin/python3 turkey_alert.py >> turkey-alert.log 2>&1

Env vars (or put them in .env, loaded automatically if present):
  EBIRD_API_KEY       required, from https://ebird.org/api/keygen
  RESEND_API_KEY      required, from https://resend.com/api-keys
  FROM_EMAIL          required, e.g. dan@danstaub.com (verified domain)
  APP_URL             required, e.g. https://alerts.danstaub.com (for unsubscribe links)
  SUBSCRIBERS_FILE    optional, default subscribers.json next to this script
  BACK_DAYS, STATE_FILE  optional (defaults below)
"""

import json
import os
import re
import sys
import urllib.parse
import urllib.request
import urllib.error
from collections import defaultdict
from datetime import datetime, timezone

BASE = os.path.dirname(os.path.abspath(__file__))
BACK_DAYS = int(os.environ.get("BACK_DAYS", "7"))
STATE_FILE = os.environ.get("STATE_FILE", os.path.join(BASE, "seen.json"))
SUBSCRIBERS_FILE = os.environ.get("SUBSCRIBERS_FILE", os.path.join(BASE, "subscribers.json"))

RESEND_URL = "https://api.resend.com/emails"
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Roswell fallback for old subscriber entries that have no lat/lng
DEFAULT_LAT, DEFAULT_LNG, DEFAULT_TOWN = 34.0232, -84.3616, "Roswell, GA"


def load_dotenv():
    path = os.path.join(BASE, ".env")
    if not os.path.exists(path):
        return
    for line in open(path):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def load_seen():
    try:
        with open(STATE_FILE) as f:
            return set(json.load(f).get("seen", []))
    except (FileNotFoundError, json.JSONDecodeError):
        return set()


def save_seen(seen):
    with open(STATE_FILE, "w") as f:
        json.dump({"seen": sorted(seen), "updated": datetime.now(timezone.utc).isoformat()}, f, indent=2)


def load_subscribers():
    try:
        with open(SUBSCRIBERS_FILE) as f:
            data = json.load(f)
        subs = data if isinstance(data, list) else data.get("subscribers", [])
    except (FileNotFoundError, json.JSONDecodeError):
        return []
    out = []
    for s in subs:
        email = s.get("email", "").lower()
        if not EMAIL_RE.match(email):
            continue
        out.append({
            "email": email,
            "town": s.get("town") or DEFAULT_TOWN,
            "lat": float(s.get("lat") or DEFAULT_LAT),
            "lng": float(s.get("lng") or DEFAULT_LNG),
            "dist_km": int(s.get("dist_km") or 40),
        })
    return out


def fetch_turkeys(api_key, lat, lng, dist_km):
    url = (
        "https://api.ebird.org/v2/data/obs/geo/recent/wiltur"
        f"?lat={lat}&lng={lng}&dist={dist_km}&back={BACK_DAYS}"
        "&maxResults=10&includeProvisional=false"
    )
    req = urllib.request.Request(url, headers={"x-ebirdapitoken": api_key, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        print(f"eBird request failed for {lat},{lng}: HTTP {e.code} {e.reason}", file=sys.stderr)
        if e.code == 403:
            print("  403 usually means a missing/invalid eBird API key.", file=sys.stderr)
        sys.exit(1)


def send_email(api_key, to_email, from_email, app_url, obs, town):
    count = obs.get("howMany") or "?"
    loc = obs.get("locName", f"near {town}")
    when = obs.get("obsDt", "recently")
    lat, lng = obs.get("lat"), obs.get("lng")
    checklist_url = f"https://ebird.org/checklist/{obs['subId']}" if obs.get("subId") else "https://ebird.org/species/wiltur"
    unsub = f"{app_url.rstrip('/')}/unsubscribe?email={urllib.parse.quote(to_email)}"
    subject = f"Wild Turkey spotted near {town} ({count} at {loc})"
    text = (
        f"A Wild Turkey was just reported near {town}.\n\n"
        f"Count: {count}\n"
        f"Location: {loc}\n"
        f"Seen: {when}\n"
        f"Coordinates: {lat}, {lng}\n"
        f"Checklist: {checklist_url}\n\n"
        f"Stop these alerts: {unsub}\n"
    )
    payload = {"from": from_email, "to": [to_email], "subject": subject, "text": text}
    req = urllib.request.Request(
        RESEND_URL,
        data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        print(f"Resend send to {to_email} failed: HTTP {e.code} {e.reason}: {e.read().decode()[:300]}", file=sys.stderr)
        return None


def main():
    load_dotenv()
    dry_run = "--dry-run" in sys.argv
    seed = "--seed" in sys.argv

    if "--test" in sys.argv:
        # No keys, no API calls: render the exact email a real sighting
        # would send, using the last known Fulton County sighting.
        from_email = os.environ.get("FROM_EMAIL", "dan@danstaub.com")
        app_url = os.environ.get("APP_URL", "https://alerts.danstaub.com")
        subscribers = load_subscribers()
        recipients = subscribers or [{"email": "test@example.com", "town": "Roswell, GA"}]
        sample = {
            "howMany": 1, "locName": "Cottages of Roswell",
            "obsDt": "2026-11-17 07:00", "lat": 34.0232, "lng": -84.3616,
            "subId": "S411265952",
        }
        for s in recipients:
            town = s.get("town", "Roswell, GA")
            to_email = s["email"]
            unsub = f"{app_url.rstrip('/')}/unsubscribe?email={urllib.parse.quote(to_email)}"
            print(f"--- TEST EMAIL to {to_email} ({town}) ---")
            print(f"From: {from_email}")
            print(f"Subject: Wild Turkey spotted near {town} (1 at Cottages of Roswell)")
            print()
            print("A Wild Turkey was just reported near Roswell, GA.")
            print()
            print("Count: 1")
            print("Location: Cottages of Roswell")
            print("Seen: 2026-11-17 07:00")
            print("Coordinates: 34.0232, -84.3616")
            print("Checklist: https://ebird.org/checklist/S411265952")
            print()
            print(f"Stop these alerts: {unsub}")
            print("--- end, nothing sent ---")
        return

    ebird_key = os.environ.get("EBIRD_API_KEY")
    resend_key = os.environ.get("RESEND_API_KEY")
    from_email = os.environ.get("FROM_EMAIL")
    app_url = os.environ.get("APP_URL", "")
    missing = [n for n, v in [("EBIRD_API_KEY", ebird_key), ("RESEND_API_KEY", resend_key),
                              ("FROM_EMAIL", from_email)] if not v]
    if missing:
        print(f"Missing required env vars: {', '.join(missing)} (see .env.example)", file=sys.stderr)
        sys.exit(1)

    subscribers = load_subscribers()
    if not subscribers:
        print("No subscribers yet in subscribers.json, nothing to check.")
        return

    # Group by location so one eBird call covers everyone in the same town
    groups = defaultdict(list)
    for s in subscribers:
        groups[(round(s["lat"], 4), round(s["lng"], 4), s["dist_km"])].append(s)

    seen = load_seen()
    total_new = 0
    for (lat, lng, dist_km), group in groups.items():
        town = group[0]["town"]
        obs_list = fetch_turkeys(ebird_key, lat, lng, dist_km)
        new = [o for o in obs_list if f"{lat},{lng}:{o.get('subId')}" not in seen]
        if seed:
            for o in obs_list:
                if o.get("subId"):
                    seen.add(f"{lat},{lng}:{o['subId']}")
            print(f"Seeded {town}: marked {len(obs_list)} current sighting(s) as seen.")
            continue
        if not new:
            print(f"{town}: no new sightings ({len(obs_list)} recent).")
            continue
        total_new += len(new)
        for obs in new:
            for s in group:
                if dry_run:
                    print(f"[dry run] Would email {s['email']} ({town}): {obs.get('howMany')} turkey(s) at "
                          f"{obs.get('locName')} on {obs.get('obsDt')} ({obs.get('subId')})")
                else:
                    result = send_email(resend_key, s["email"], from_email, app_url, obs, town)
                    if result:
                        print(f"Emailed {s['email']} ({town}): {obs.get('howMany')} turkey(s) at "
                              f"{obs.get('locName')} on {obs.get('obsDt')}. Resend id: {result.get('id')}")
            if obs.get("subId"):
                seen.add(f"{lat},{lng}:{obs['subId']}")
    save_seen(seen)
    if seed:
        print("Seeded, sent nothing.")
    elif total_new == 0:
        print("No new sightings in any town.")


if __name__ == "__main__":
    main()
