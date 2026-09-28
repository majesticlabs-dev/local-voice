#!/usr/bin/env python3
"""Exercise the Chrome extension HTTP contract against a running packaged service."""
import json
import sys
import time
import urllib.error
import urllib.request

base = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else "http://127.0.0.1:5517"
origin = "chrome-extension://abcdefghijklmnopabcdefghijklmnop"


def call(path, method="GET", body=None, extra=None):
    headers = {"Origin": origin, **(extra or {})}
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=120) as response:
        payload = response.read()
        assert response.headers.get("Access-Control-Allow-Origin") == "*", path
        return response.status, response.headers, payload


for path in ("/health", "/voices"):
    status, _, payload = call(path)
    body = json.loads(payload)
    if path == "/health":
        assert body["status"] == "ok" and body["ready"] is True
        assert next(d for d in body["dependencies"] if d["name"] == "piper")["required"] is False
    else:
        assert any(voice["id"] == "af_bella" and voice["available"] for voice in body["voices"])
    print(path, status)

for path in ("/synthesize", "/stream", "/stop"):
    req = urllib.request.Request(base + path, headers={
        "Origin": origin, "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type",
    }, method="OPTIONS")
    with urllib.request.urlopen(req, timeout=10) as response:
        assert response.status == 200
        assert response.headers["Access-Control-Allow-Origin"] == "*"
        assert "POST" in response.headers["Access-Control-Allow-Methods"]
        assert "content-type" in response.headers["Access-Control-Allow-Headers"].lower()
        print("OPTIONS", path, response.status)

status, headers, audio = call("/synthesize", "POST", {
    "text": "Chrome extension packaged service test.", "voice": "af_bella", "rate": 1.0,
    "format": "mp3", "lang": "en", "session_id": "c1-synth", "normalize_audio": True,
}, {"Content-Type": "application/json"})
assert status == 200 and len(audio) > 1000 and headers["Content-Type"].startswith("audio/mpeg")
print("/synthesize", status, len(audio))

status, _, payload = call("/stream", "POST", {
    "text": "Packaged streaming test.", "voice": "af_bella", "rate": 1.0,
    "format": "mp3", "chunking": {"strategy": "sentence", "target_chars": 500, "max_chars": 1000},
    "session_id": "c1-stream",
}, {"Content-Type": "application/json"})
job = json.loads(payload)
assert status == 200 and job["chunks"]
print("/stream", status, len(job["chunks"]))

url = job["chunks"][0]["url"]
for _ in range(60):
    try:
        status, headers, audio = call(url)
        assert len(audio) > 1000 and headers["Content-Type"].startswith("audio/mpeg")
        print(url, status, len(audio))
        break
    except urllib.error.HTTPError as exc:
        if exc.code != 425:
            raise
        time.sleep(0.25)
else:
    raise AssertionError("Chunk never became ready")

status, _, _ = call("/stop", "POST", {"job_id": job["job_id"]}, {"Content-Type": "application/json"})
assert status == 200
print("/stop", status)
