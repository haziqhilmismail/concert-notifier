import html, json, os, re, subprocess, sys, time, urllib.error, urllib.parse, urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).parent
SEEN_FILE = HERE / "seen.json"
ALERTS_FILE = HERE / "alerts.json"
HOMER_PAGE = Path.home() / "homer/data/concerts.yml"
TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
EDITOR_URL = os.environ.get("EDITOR_URL") or "http://localhost:8095"
CLAUDE = Path.home() / ".local/bin/claude"  # full path: systemd's PATH has no ~/.local/bin
SCHEMA = json.dumps({"type": "object", "required": ["alerts"], "properties": {"alerts": {
    "type": "array", "items": {"type": "object", "required": ["summary", "headlines"], "properties": {
        "summary": {"type": "string"}, "headlines": {"type": "array", "items": {"type": "integer"}}}}}}})
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64)"}
EDITIONS = (("en-MY", "MY", "MY:en"), ("ms", "MY", "MY:ms"), ("id", "ID", "ID:id"), ("ja", "JP", "JP:ja"))
FOREIGN_TERMS = ('Malaysia OR Singapore OR "Kuala Lumpur" OR Asia OR tour OR '
                 'マレーシア OR シンガポール OR アジア OR ツアー')
LOCAL_TERMS = "concert OR konsert OR konser OR tour OR jelajah"


def load_artists():
    artists = {}
    for line in (HERE / "artists.txt").read_text().splitlines():
        names, _, tag = line.partition("|")
        names = [n.strip() for n in names.split("/") if n.strip()]
        if names:
            artists.setdefault(names[0].lower(), (names, tag.strip().lower() == "local"))
    return list(artists.values())


def names_in(names, title):
    # Japanese titles have no spaces, so only ASCII names need word boundaries.
    return any(re.search(rf"(?<!\w){re.escape(n)}(?!\w)" if n.isascii() else re.escape(n),
                         title, 0 if len(n) <= 3 else re.I)
               for n in names)


assert names_in(["幾田りら"], "幾田りらがアジアツアー開催") and not names_in(["Ado"], "tornado ADO")


def fetch(q, hl, gl, ceid):
    url = "https://news.google.com/rss/search?" + urllib.parse.urlencode(
        {"q": q, "hl": hl, "gl": gl, "ceid": ceid})
    for attempt in range(3):
        try:
            root = ET.fromstring(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20).read())
            break
        except urllib.error.HTTPError:
            if attempt == 2:
                raise
            time.sleep(10)
    return [(i.findtext("title"), i.findtext("link")) for i in root.iter("item")]


def search(names, local):
    who = " OR ".join(f'"{n}"' for n in names)
    q = f"({who}) ({LOCAL_TERMS if local else FOREIGN_TERMS}) when:30d"
    hits = {}
    for edition in EDITIONS:
        for title, link in fetch(q, *edition):
            if names_in(names, title):
                hits.setdefault(link, title)
    return [(t, l) for l, t in hits.items()]


class ClaudeError(Exception):
    pass


def classify(artist, local, headlines, past_alerts):
    scope = (f"{artist} is a Malaysian artist. Alert on any concert, tour or festival show by them, in any country."
             if local else
             f"Alert when {artist} performs or appears in Malaysia or Singapore: concert, tour date, festival, "
             "showcase, fan meeting, street performance or visit. Also alert on a new tour announcement whose stops "
             "include Southeast Asia, or whose stops are not announced yet. Skip a tour whose announced stops are all "
             "outside Southeast Asia (for example only East Asia and Australia), and skip later news about such a tour: "
             "venues, final show, title changes, added or dropped stops that are not in Southeast Asia.")
    prompt = f"""You filter news headlines for a fan in Malaysia who follows {artist}.
{scope}
Ticket sales, new dates and venue news for such a show also count.
Skip gossip, personal life, new songs and interviews.
Skip shows in other countries, and tours that only cover other regions (for example North America or Europe only).
Today is {time.strftime("%Y-%m-%d")}. Skip shows and tours that already ended.

Alerts already sent for {artist} (newest last):
{json.dumps(past_alerts[-15:], ensure_ascii=False)}
Skip a headline that only repeats news in those alerts. Alert if it adds a new fact
(for example: a Malaysia date after an Asia tour announcement, or ticket sale dates).
Put headlines about the same news into one alert.

Headlines (any language):
{json.dumps(dict(enumerate(headlines)), ensure_ascii=False)}

For each alert, write a one-sentence English summary with the date, city and venue if the headline gives them."""
    # Uses the subscription login in ~/.claude, so ANTHROPIC_API_KEY is removed from env.
    env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
    out = subprocess.run(
        [CLAUDE, "-p", "--model", "sonnet", "--tools", "", "--setting-sources", "",
         "--strict-mcp-config", "--no-session-persistence", "--disable-slash-commands",
         "--output-format", "json", "--json-schema", SCHEMA],
        input=prompt, capture_output=True, text=True, timeout=300, cwd=HERE, env=env)
    try:
        res = json.loads(out.stdout)
    except ValueError:
        raise ClaudeError(f"exit {out.returncode}: {(out.stderr or out.stdout)[-300:]}")
    if res.get("is_error") or out.returncode:
        raise ClaudeError(res.get("result") or f"exit {out.returncode}")
    alerts = res["structured_output"]["alerts"]
    return [(a["summary"], [i for i in a["headlines"] if 0 <= i < len(headlines)]) for a in alerts]


def save(path, obj):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1))
    os.replace(tmp, path)


def send(text):
    if not TOKEN:
        print(text, "\n")
        return
    text = "<b>[CONCERT]</b>\n" + text
    data = urllib.parse.urlencode({"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"}).encode()
    urllib.request.urlopen(f"https://api.telegram.org/bot{TOKEN}/sendMessage", data, timeout=20)


def main():
    seen = set(json.loads(SEEN_FILE.read_text())) if SEEN_FILE.exists() else set()
    alerts = json.loads(ALERTS_FILE.read_text()) if ALERTS_FILE.exists() else {}
    first_run = not seen
    claude_error = None
    for names, local in load_artists():
        artist = names[0]
        try:
            new = [(t, l) for t, l in search(names, local) if l not in seen]
            if not new:
                continue
            if first_run:
                seen.update(l for _, l in new)
                continue
            found = classify(artist, local, [t for t, _ in new], [a["summary"] for a in alerts.get(artist, [])])
        except ClaudeError as e:
            print(f"{artist}: Claude Code failed: {e}", file=sys.stderr)
            claude_error = e
            continue
        except Exception as e:
            print(f"{artist}: failed: {e}", file=sys.stderr)
            continue
        for summary, idx in found:
            # Google News titles end in " - <site>": show the site name as the link text.
            links = " · ".join(f'<a href="{html.escape(new[i][1])}">{html.escape(new[i][0].rsplit(" - ", 1)[-1])}</a>'
                               for i in idx[:2])
            try:
                send(f"🎤 <b>{html.escape(artist)}</b>\n{html.escape(summary)}\n{links}")
            except Exception as e:
                print(f"{artist}: Telegram send failed: {e}", file=sys.stderr)
            alerts.setdefault(artist, []).append(
                {"summary": summary, "link": new[idx[0]][1] if idx else "", "date": time.strftime("%Y-%m-%d")})
        seen.update(l for _, l in new)
        save(SEEN_FILE, sorted(seen))
        save(ALERTS_FILE, alerts)
    save(SEEN_FILE, sorted(seen))
    write_homer_page(alerts)
    if claude_error:
        send("⚠️ <b>Concert notifier: Claude Code failed</b>\n"
             f"<code>{html.escape(str(claude_error))}</code>\n"
             "If it says login: SSH to the server, run <code>claude</code>, then <code>/login</code>. "
             "Missed headlines are checked again on the next run.")


def write_homer_page(alerts):
    # JSON is valid YAML, so no yaml library is needed.
    if not HOMER_PAGE.parent.exists():
        return
    latest = sorted(((a["date"], artist, a) for artist, items in alerts.items() for a in items),
                    key=lambda x: x[0], reverse=True)[:30]
    items = [{"name": artist, "subtitle": a["summary"], "tag": date, "url": a["link"], "target": "_blank",
              "icon": "fas fa-music"} for date, artist, a in latest]
    edit = {"name": "Edit artist list", "subtitle": "Add or remove artists", "icon": "fas fa-pen",
            "url": EDITOR_URL, "target": "_blank"}
    page = {"subtitle": "Concert news", "message": None, "services": [
        {"name": "Artists", "icon": "fas fa-list", "items": [edit]},
        {"name": "Concert news (Malaysia / Singapore)", "icon": "fas fa-microphone", "items": items}]}
    save(HOMER_PAGE, page)


if __name__ == "__main__":
    main()
