#!/usr/bin/env python3
"""Live test for the turkey alert app. Starts the signup server, signs
up a test email for Roswell, renders a test alert, unsubscribes, and
leaves subscribers.json empty. No keys, no real emails sent."""
import json
import subprocess
import sys
import time
import urllib.request
import urllib.parse

BASE = "/home/hatch/workspace/turkey-alert"

server = subprocess.Popen(
    [sys.executable, "server.py"], cwd=BASE,
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
)
try:
    time.sleep(1.5)
    # 1. Signup page loads
    page = urllib.request.urlopen("http://localhost:8000/", timeout=5).read().decode()
    assert "Roswell, GA" in page and "Or any other town" in page
    print("1. Signup page loads, Roswell + custom town field present: OK")

    # 2. Subscribe test@example.com for Roswell, GA
    data = urllib.parse.urlencode({"email": "test@example.com", "town": "Roswell, GA"}).encode()
    resp = urllib.request.urlopen(urllib.request.Request("http://localhost:8000/subscribe", data=data), timeout=5).read().decode()
    assert "You're in, test@example.com" in resp
    print("2. Subscribe test@example.com for Roswell, GA: OK")
    print("   subscribers.json:", open(f"{BASE}/subscribers.json").read().strip().replace("\n", " "))

    # 3. Render the test alert email (no keys, no API calls, nothing sent)
    out = subprocess.run([sys.executable, "turkey_alert.py", "--test"], cwd=BASE, capture_output=True, text=True, timeout=10)
    print("3. Test alert email:")
    print(out.stdout)

    # 4. Unsubscribe
    resp = urllib.request.urlopen("http://localhost:8000/unsubscribe?email=test@example.com", timeout=5).read().decode()
    assert "is unsubscribed" in resp
    print("4. Unsubscribe test@example.com: OK")
    print("   subscribers.json:", open(f"{BASE}/subscribers.json").read().strip())
finally:
    server.terminate()
    server.wait(timeout=5)
print("TEST PASSED")
