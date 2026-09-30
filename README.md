# x-delete

Local, FOSS tool to delete your own X (Twitter) posts when they match rules you define (age, likes, reposts, and so on). Runs on your Mac, uses the official X API only, and keeps credentials and state on disk.

No third-party services. No pip dependencies — Python 3 stdlib only.

## What it does

1. **Preview** — Fetches your recent posts from X, applies your rules, and prints what would be deleted (nothing is removed).
2. **Delete** — Removes posts from a local queue, up to a per-run cap, via `DELETE /2/tweets/:id`.

A post is classified as **tweets**, **replies**, or **reposts**, and as **text** or **media** (photo/video/GIF on the post). Only the rule list for that category applies. A post is deleted when **any** rule in its category matches; within one rule, every condition must match (AND).

## Limits and cost

- The user timeline API returns at most the **3,200 most recent** posts. This tool is for ongoing cleanup, not wiping an entire archive.
- Replies are included by default. The API only returns the **800 most recent** posts if you use `exclude=replies`; this tool filters replies locally so you keep the 3,200 window.
- X uses **pay-per-use** credits (check the [Developer Console](https://developer.x.com) for current rates). Typical ballpark: about **$0.001** per own post read and **$0.010** per delete. Set a spending cap in the console before running at scale.
- Delete rate limits apply (on the order of tens per 15 minutes per user). The script backs off on HTTP 429.

## X developer setup

1. Sign in at [developer.x.com](https://developer.x.com) and create a **Project** and **App**.
2. Enable **Read and write** (or equivalent write access for managing posts).
3. Generate **OAuth 1.0a** user access tokens for **your** account (API key, API secret, access token, access token secret).
4. Add credits and a spending limit in the Developer Console.

Copy the example files and fill in secrets locally (never commit them):

```bash
cp config.example.jsonc config.json
cp .env.example .env
# edit config.json and .env
```

## Configuration

See [config.example.jsonc](config.example.jsonc). The example uses `//` line comments; `config.json` may use the same (they are stripped before parsing).

OAuth 1.0a credentials live in [`.env.example`](.env.example) (copy to `.env`):

| Variable | Meaning |
| --- | --- |
| `X_API_KEY` | App API key (consumer key) |
| `X_API_SECRET` | App API secret |
| `X_ACCESS_TOKEN` | Your user access token |
| `X_ACCESS_TOKEN_SECRET` | Your user access token secret |

Environment variables override values from the `.env` file. Optional flag: `--env /path/to/.env`.

Top-level fields:

| Field | Meaning |
| --- | --- |
| `min_age_days` | Safety floor; no rule may use `older_than_days` below this |
| `max_deletes_per_run` | Cap deletions per `delete --apply` run |

Categories: `tweets`, `replies`, and `reposts`. Each has `text` and `media` buckets:

| Bucket | Meaning |
| --- | --- |
| `tweets.text` | Original posts with no media attachment |
| `tweets.media` | Original posts with photo, video, or GIF |
| `replies.text` / `replies.media` | Your replies, split the same way |
| `reposts.text` / `reposts.media` | Retweets (reposts). Use `null` or `"enabled": false` to skip |

Each bucket is either `null` (disabled) or an object with a `rules` array.

Each rule:

| Field | Required | Meaning |
| --- | --- | --- |
| `older_than_days` | yes | Post must be at least this old |
| `max_likes` | no | Delete if like count is **strictly less than** this |
| `max_reposts` | no | Same for reposts |
| `max_replies` | no | Same for reply count on that post |
| `max_quotes` | no | Same for quote posts |

Media detection uses `attachments.media_keys` on the timeline post. A plain retweet without attachment metadata is treated as **text**.

## Usage

From the repo directory:

```bash
python3 xdelete.py self-check          # offline sanity check
python3 xdelete.py preview             # fetch + print matches; no state change
python3 xdelete.py preview --update-state   # also refresh queue in state.json
python3 xdelete.py delete              # show what the queue head would delete
python3 xdelete.py delete --apply      # actually delete (up to cap)
```

Recommended first run:

```bash
python3 xdelete.py preview
```

When the list looks correct:

```bash
python3 xdelete.py preview --update-state
python3 xdelete.py delete --apply
```

`state.json` holds `last_fetch_at` and the deletion queue. The fetch watermark advances only after a successful `preview --update-state`.

## Daily automation (macOS launchd)

Only install this after preview looks right.

1. Copy [com.xdelete.plist.example](com.xdelete.plist.example) to `~/Library/LaunchAgents/com.xdelete.plist`.
2. Replace every `/ABSOLUTE/PATH/TO/x-delete` with this repo’s path.
3. Load the job:

```bash
launchctl load ~/Library/LaunchAgents/com.xdelete.plist
```

The example runs at 03:00 daily: `preview --update-state`, then `delete --apply`. Logs go to `xdelete.log` in the repo (gitignored if you add `*.log` — already in `.gitignore`).

Unload:

```bash
launchctl unload ~/Library/LaunchAgents/com.xdelete.plist
```

## Privacy

- `.env`, `config.json`, and `state.json` stay on your machine (see [.gitignore](.gitignore)).
- Network traffic goes to `api.x.com` only, with your OAuth 1.0a user tokens.

## License

MIT — see [LICENSE](LICENSE).
