<p align="center"><img src="logo.svg" width="96" alt="Concert notifier logo"></p>

# Concert notifier

The concert notifier sends a Telegram message when an artist that you follow announces a concert in Malaysia or Singapore.

## How it works

1. It reads the artist list in `artists.txt`.
2. It searches Google News (English, Malay, Indonesian and Japanese editions) for each artist.
3. It sends the new headlines to Claude Code (`claude -p`, Sonnet). Claude Code keeps only the headlines about shows and writes a one-sentence summary of each.
4. It sends each summary to Telegram.
5. It writes the 30 newest alerts to `~/homer/data/concerts.yml`. The `concerts.html` tile on the Homarr board reads this file.

For a foreign artist, it alerts on shows in Malaysia or Singapore, and on new tours that include Southeast Asia. For an artist with `| local`, it alerts on all concerts and tours.

## Run it with systemd

- `concert-notifier.timer` (systemd user timer) starts `notifier.py` every 6 hours (00:00, 06:00, 12:00, 18:00 Malaysia time).
- `concert-editor.service` (systemd user service) runs `editor.py`. This is a small web page on port 8095 to edit `artists.txt`.
  The editor has no password. It accepts a save only from its own page, at an IP address, a one-word host name, or a `.ts.net` name. Do not open port 8095 to the internet.

Both units are in `~/.config/systemd/user/`. The notifier unit loads `.env` with `EnvironmentFile=`.

## Set it up

1. Install Python 3 and Claude Code (`~/.local/bin/claude`). Log in to Claude Code once.
2. Copy `.env.example` to `.env` and set the values:
   - `TELEGRAM_TOKEN`: the Telegram bot token.
   - `TELEGRAM_CHAT_ID`: the chat that gets the alerts.
   - `EDITOR_URL`: the URL of `editor.py`, for the link on the Homer page.
3. Put one artist per line in `artists.txt`. Write other spellings after `/`. Add `| local` for a Malaysian artist.
4. Run `python3 notifier.py` once. The first run for each artist only records the current headlines, so you do not get old news. This is also true for an artist that you add later.

If `TELEGRAM_TOKEN` is empty, the script prints the alerts and sends nothing.

## Files

```
notifier.py    search, filter with Claude Code, send to Telegram
editor.py      web editor for artists.txt (port 8095)
artists.txt    the artists to follow
.env.example   the env vars, with empty values
seen.json      headlines already checked (runtime state, not in git)
alerts.json    alerts already sent (runtime state, not in git)
seeded.json    artists that had their first run (runtime state, not in git)
```
