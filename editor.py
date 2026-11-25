import html, ipaddress, os, urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ARTISTS = Path(__file__).parent / "artists.txt"
PAGE = """<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Concert artists</title>
<style>body{{font:16px system-ui;max-width:640px;margin:24px auto;padding:0 16px;color-scheme:light dark}}
textarea{{width:100%;height:60vh;font:15px ui-monospace,monospace;box-sizing:border-box}}
button{{font-size:16px;padding:8px 20px;margin-top:8px}}small{{opacity:.7}}</style>
<h2>🎤 Concert artists</h2>{msg}
<form method="post"><textarea name="artists" autofocus>{text}</textarea>
<button>Save</button></form>
<p><small>One artist per line. Other spellings after <code>/</code>, e.g. <code>Lilas Ikuta / 幾田りら</code>.
Add <code>| local</code> for a Malaysian artist, e.g. <code>Anuar Zain | local</code>.
Changes apply on the next check (every 6 hours).</small></p>"""


def trusted_host(host):
    # DNS rebinding needs a public domain name. IPs, single-label names and the tailnet are safe.
    name = urllib.parse.urlsplit("//" + host).hostname or ""
    try:
        ipaddress.ip_address(name)
        return True
    except ValueError:
        return "." not in name or name.endswith(".ts.net")


class Handler(BaseHTTPRequestHandler):
    def page(self, msg=""):
        body = PAGE.format(msg=msg, text=html.escape(ARTISTS.read_text())).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self.page()

    def do_POST(self):
        host, origin = self.headers.get("Host", ""), self.headers.get("Origin")
        if not trusted_host(host) or (origin and urllib.parse.urlsplit(origin).netloc != host):
            self.send_error(403)
            return
        size = int(self.headers.get("Content-Length", 0))
        if not 0 <= size <= 100_000:
            self.send_error(413)
            return
        form = urllib.parse.parse_qs(self.rfile.read(size).decode(), keep_blank_values=True)
        text = form.get("artists", [""])[0].replace("\r\n", "\n").strip() + "\n"
        tmp = ARTISTS.with_suffix(".tmp")
        tmp.write_text(text)
        os.replace(tmp, ARTISTS)
        count = sum(1 for line in text.splitlines() if line.strip())
        self.page(f"<p>✅ Saved {count} artists.</p>")


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8095), Handler).serve_forever()
