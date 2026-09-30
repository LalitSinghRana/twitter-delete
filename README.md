# twitter-delete

Deletes your own Twitter posts that are older than "N" days and have fewer than "M" likes. It runs in the browser on the [x.com](https://x.com) tab you are already logged into. No API keys.

## Install

1. Open [`twitter-delete.txt`](twitter-delete.txt), select all, copy (one line starting with `javascript:`).
2. In your browser’s bookmark manager, **Add bookmark** → name **twitter-delete** → paste into **URL** → Save.

## Use

1. Log in to Twitter at [x.com](https://x.com).
2. Open your profile with replies: `https://x.com/YOUR_HANDLE/with_replies`
3. Click the **twitter-delete** bookmark.
4. Set **Older than (days)** and **Fewer than (likes)**, then click **Scan**.
5. Uncheck anything you want to keep, then click **Delete selected**.

## Limits

Only posts Twitter loads while the script scrolls your timeline are considered—not your full archive. Twitter’s display language must be **English** so the Delete menu can be found.

## Dev

Edit `twitter-delete.script.js`, then regenerate and commit `twitter-delete.txt` (CI enforces this on PRs to `main`):

```bash
node twitter-delete.script.js --write-bookmark
git add twitter-delete.txt
```

MIT — see [LICENSE](LICENSE).
