from http.server import BaseHTTPRequestHandler
import urllib.parse
import json

# Simple in-memory store (resets on cold start)
DATA = {
    "uid": "",
    "total_needed": 0,
    "total_success": 0
}

HTML = """
<!DOCTYPE html>
<html>
<head>
  <title>Premium Visit Tracker</title>
  <style>
    body { font-family: Arial; background:#0f172a; color:#e5e7eb; }
    .box { max-width:420px; margin:40px auto; background:#020617; padding:20px; border-radius:12px; }
    input,button { width:100%; padding:10px; margin-top:10px; border-radius:8px; border:none; }
    button { background:#22c55e; font-weight:bold; cursor:pointer; }
  </style>
</head>
<body>
<div class="box">
<h2>Premium Visit Tracker</h2>
<form method="POST">
<input name="uid" placeholder="UID" value="{uid}">
<input name="total_needed" type="number" placeholder="Total visits needed" value="{total_needed}">
<input name="success" type="number" placeholder="Success (e.g. 1753)">
<button>Add Success</button>
</form>
<p><b>Total Success:</b> {total_success}</p>
<p><b>Remaining:</b> {remaining}</p>
{done}
</div>
</body>
</html>
"""

class handler(BaseHTTPRequestHandler):

    def do_GET(self):
        self.respond()

    def do_POST(self):
        length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(length).decode()
        data = urllib.parse.parse_qs(body)

        if "uid" in data and data["uid"][0]:
            DATA["uid"] = data["uid"][0]

        if "total_needed" in data and data["total_needed"][0]:
            DATA["total_needed"] = int(data["total_needed"][0])

        if "success" in data and data["success"][0]:
            DATA["total_success"] += int(data["success"][0])

        self.respond()

    def respond(self):
        remaining = max(DATA["total_needed"] - DATA["total_success"], 0)
        done = "<p style='color:#22c55e'>✅ Target Completed</p>" if remaining == 0 and DATA["total_needed"] else ""

        page = HTML.format(
            uid=DATA["uid"],
            total_needed=DATA["total_needed"],
            total_success=DATA["total_success"],
            remaining=remaining,
            done=done
        )

        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(page.encode())
