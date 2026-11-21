#!/usr/bin/env python3
"""
Turkey alert signup page - stdlib only, no dependencies.

Serves a signup form at / and stores emails in subscribers.json.
Each subscriber picks a town, so alerts are per-town, not just Roswell.

  GET  /                        signup form (town dropdown + custom town)
  POST /subscribe               fields: email, town, custom_town
  GET  /unsubscribe?email=...   removes an email, shows confirmation

Towns: a preset list of Georgia towns with hardcoded coordinates for
one-tap signup. Any other town can be typed in; it is geocoded via
Nominatim (OpenStreetMap, free, no key) and stored with its lat/lng.
This reuses the pattern from Dan's eBird region finder
(ebird.danstaub.com), which already does lat/lng + distance lookup.

Run:  python3 server.py            (http://localhost:8000)
      PORT=8000 python3 server.py
"""

import json
import os
import re
import sys
import threading
import time
import urllib.parse
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BASE = os.path.dirname(os.path.abspath(__file__))
SUBSCRIBERS_FILE = os.environ.get("SUBSCRIBERS_FILE", os.path.join(BASE, "subscribers.json"))
PORT = int(os.environ.get("PORT", "8000"))
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Preset towns: name -> (lat, lng). Roswell is the default.
TOWNS = {
    "Roswell, GA": (34.0232, -84.3616),
    "Alpharetta, GA": (34.0754, -84.2941),
    "Marietta, GA": (33.9526, -84.5499),
    "Sandy Springs, GA": (33.9304, -84.3733),
    "Atlanta, GA": (33.7490, -84.3880),
    "Decatur, GA": (33.7748, -84.2963),
    "Athens, GA": (33.9519, -83.3576),
    "Savannah, GA": (32.0809, -81.0912),
    "Augusta, GA": (33.4735, -82.0105),
    "Columbus, GA": (32.4609, -84.9877),
    "Macon, GA": (32.8407, -83.6324),
    "Gainesville, GA": (34.2979, -83.8247),
    "Charlotte, NC": (35.2271, -80.8431),
}
DEFAULT_TOWN = "Roswell, GA"


def load_subscribers():
    try:
        with open(SUBSCRIBERS_FILE) as f:
            data = json.load(f)
        return data if isinstance(data, list) else data.get("subscribers", [])
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def save_subscribers(subs):
    with open(SUBSCRIBERS_FILE, "w") as f:
        json.dump(subs, f, indent=2)


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


def send_welcome_email(email, town_name):
    """Welcome email on signup, via Resend. Returns True if sent.

    Never blocks signup: if keys are missing or Resend fails, log it
    and let the signup page still confirm. The sender is FROM_EMAIL
    (dan@danstaub.com), so this also tells the subscriber which address
    future turkey alerts will come from.
    """
    load_dotenv()
    api_key = os.environ.get("RESEND_API_KEY")
    from_email = os.environ.get("FROM_EMAIL")
    app_url = os.environ.get("APP_URL", "https://alerts.danstaub.com")
    if not api_key or not from_email:
        print("Welcome email skipped: RESEND_API_KEY or FROM_EMAIL not set.", file=sys.stderr)
        return False
    unsub = f"{app_url.rstrip('/')}/unsubscribe?email={urllib.parse.quote(email)}"
    payload = {
        "from": from_email,
        "to": [email],
        "subject": f"You're in, Turkey Alert is on for {town_name}",
        "text": (
            f"You're all set for Turkey Alert.\n\n"
            f"You will get an email from {from_email} whenever a Wild Turkey "
            f"is reported on eBird within 25 miles of {town_name}.\n\n"
            f"Turkeys are rare in most towns, so expect silence most weeks, "
            f"not spam. One email per sighting.\n\n"
            f"Stop these alerts: {unsub}\n"
        ),
    }
    req = urllib.request.Request(
        "https://api.resend.com/emails",
        data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.load(resp)
        print(f"Welcome email sent to {email} ({town_name}). Resend id: {result.get('id')}", file=sys.stderr)
        return True
    except urllib.error.HTTPError as e:
        print(f"Welcome email to {email} failed: HTTP {e.code} {e.reason}: {e.read().decode()[:300]}", file=sys.stderr)
        return False
    except Exception as e:
        print(f"Welcome email to {email} failed: {e}", file=sys.stderr)
        return False


def geocode_town(query):
    """Free geocode via Nominatim. Returns (display_name, lat, lng) or None."""
    url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(
        {"q": query, "format": "json", "limit": 1}
    )
    req = urllib.request.Request(url, headers={"User-Agent": "turkey-alert/1.0 (danstaub.com)"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            results = json.load(resp)
    except (urllib.error.URLError, urllib.error.HTTPError):
        return None
    if not results:
        return None
    r = results[0]
    return (r.get("display_name", query), float(r["lat"]), float(r["lon"]))


def town_options(selected):
    out = []
    for name in TOWNS:
        sel = " selected" if name == selected else ""
        out.append(f'<option value="{name}"{sel}>{name}</option>')
    return "\n".join(out)


def page(message="", selected=DEFAULT_TOWN):
    return f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Turkey Alert</title>
<style>
body {{ font-family: system-ui, sans-serif; max-width: 560px; margin: 4rem auto; padding: 0 1rem; line-height: 1.5; }}
h1 {{ font-size: 1.8rem; }} input, select, button {{ font-size: 1rem; padding: .6rem; margin: .25rem 0; }}
input, select {{ width: 100%; box-sizing: border-box; }} button {{ cursor: pointer; }}
label {{ font-weight: 600; display: block; margin-top: 1rem; }}
.note {{ color: #555; font-size: .9rem; }}
</style></head>
<body>
<h1>🦃 Turkey Alert</h1>
<p>Get an email when a Wild Turkey is reported on eBird within 25 miles of the town you pick.</p>
<p class="note">Turkeys are rare in most towns, so expect silence most weeks, not spam. One email per sighting, unsubscribe in every email.</p>
{message}
<form method="post" action="/subscribe">
<label for="email">Email</label>
<input type="email" id="email" name="email" placeholder="you@example.com" required>
<label for="town">Town</label>
<select id="town" name="town">
{town_options(selected)}
</select>
<label for="custom_town">Or any other town</label>
<input type="text" id="custom_town" name="custom_town" placeholder="e.g. Asheville, NC (leave blank to use the town above)">
<button type="submit">Notify me</button>
</form>
</body></html>
"""


class Handler(BaseHTTPRequestHandler):
    def _send(self, html, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html.encode())

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/unsubscribe":
            email = urllib.parse.parse_qs(parsed.query).get("email", [""])[0].lower().strip()
            subs = load_subscribers()
            kept = [s for s in subs if s.get("email", "").lower() != email]
            if len(kept) != len(subs):
                save_subscribers(kept)
                msg = f"<p><strong>{email}</strong> is unsubscribed. No more turkey alerts.</p>"
            else:
                msg = "<p>That email was not on the list.</p>"
            return self._send(page(msg))
        return self._send(page())

    def do_POST(self):
        if urllib.parse.urlparse(self.path).path != "/subscribe":
            return self._send("Not found", 404)
        length = int(self.headers.get("Content-Length", 0))
        fields = urllib.parse.parse_qs(self.rfile.read(length).decode())
        email = fields.get("email", [""])[0].lower().strip()
        town = fields.get("town", [DEFAULT_TOWN])[0]
        custom = fields.get("custom_town", [""])[0].strip()
        if not EMAIL_RE.match(email):
            return self._send(page("<p><strong>That does not look like an email address.</strong></p>"), 400)

        if custom:
            found = geocode_town(custom)
            if not found:
                return self._send(
                    page(f"<p><strong>Could not find '{custom}'.</strong> Try a town and state, like Asheville, NC.</p>"),
                    400,
                )
            town_name, lat, lng = found
            # Shorten Nominatim's long display name to "Town, State" when possible
            parts = [p.strip() for p in town_name.split(",")]
            town_name = ", ".join(parts[:2]) if len(parts) >= 2 else town_name
        else:
            lat, lng = TOWNS.get(town, TOWNS[DEFAULT_TOWN])
            town_name = town

        subs = load_subscribers()
        existing = [s for s in subs if s.get("email", "").lower() == email]
        if existing:
            # Same person picking a new town: update their town, don't duplicate
            existing[0].update({"town": town_name, "lat": lat, "lng": lng, "dist_km": 40})
            save_subscribers(subs)
            msg = f"<p><strong>Updated, {email}.</strong> You will now get turkey alerts for {town_name}.</p>"
        else:
            from datetime import datetime, timezone
            subs.append({
                "email": email, "town": town_name, "lat": lat, "lng": lng, "dist_km": 40,
                "subscribed_at": datetime.now(timezone.utc).isoformat(),
            })
            save_subscribers(subs)
            from_email = os.environ.get("FROM_EMAIL", "dan@danstaub.com")
            welcome_sent = send_welcome_email(email, town_name)
            if welcome_sent:
                msg = (f"<p><strong>You're in, {email}.</strong> You will get an email the next time a Wild Turkey "
                       f"is reported near {town_name}. A welcome email is on its way from {from_email}, "
                       f"future alerts will come from that same address.</p>")
            else:
                msg = f"<p><strong>You're in, {email}.</strong> You will get an email the next time a Wild Turkey is reported near {town_name}.</p>"
        return self._send(page(msg, selected=town_name if town_name in TOWNS else DEFAULT_TOWN))

    def log_message(self, *args):
        pass


def poll_loop():
    """Run the eBird poller in-process every 30 minutes.

    This runs in the same container as the signup page, so it shares
    subscribers.json and seen.json with it. A separate Railway cron
    service would NOT see those files: Railway gives each service its
    own ephemeral filesystem, and volumes cannot be shared between
    services, so a separate cron would find zero subscribers every run
    and re-email the same sightings. Do not split this out again.
    """
    try:
        import turkey_alert
    except ImportError as e:
        print(f"Poller disabled: cannot import turkey_alert: {e}", file=sys.stderr)
        return
    interval = int(os.environ.get("POLL_INTERVAL_SECONDS", "1800"))
    state_file = os.environ.get("STATE_FILE", os.path.join(BASE, "seen.json"))
    first = not os.path.exists(state_file)
    while True:
        argv = ["turkey_alert.py", "--seed"] if first else ["turkey_alert.py"]
        first = False
        saved_argv = sys.argv
        sys.argv = argv
        try:
            turkey_alert.main()
        except SystemExit as e:
            # Missing keys, eBird 403, etc: log and retry next interval,
            # do not kill the web server.
            print(f"Poller run exited ({e.code}), will retry in {interval}s.", file=sys.stderr)
        except Exception as e:
            print(f"Poller run failed: {e}, will retry in {interval}s.", file=sys.stderr)
        finally:
            sys.argv = saved_argv
        time.sleep(interval)


if __name__ == "__main__":
    print(f"Turkey alert signup running on http://localhost:{PORT}")
    if os.environ.get("DISABLE_POLLER", "") != "1":
        threading.Thread(target=poll_loop, daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
