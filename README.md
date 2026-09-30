# twitter-delete

Deletes your own Twitter posts that are older than "N" days and have fewer than "M" likes. It runs in the browser on the [x.com](https://x.com) tab you are already logged into. No API keys.

## Install

1. Open [`bookmarklet.url.txt`](bookmarklet.url.txt), select all, copy (one line starting with `javascript:`).
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

After editing `twitter-delete.js`, regenerate and commit the bookmark outputs (CI enforces this on PRs to `main`):

```bash
node twitter-delete.js        # matcher self-check
node build-bookmarklet.js     # writes bookmarklet.url.txt + bookmarklet.html
git add bookmarklet.url.txt bookmarklet.html
```

Optional local hook: run `node build-bookmarklet.js` before commit when `twitter-delete.js` changed. You do not need a separate “build step” on push—GitHub Actions runs the same check and fails the merge if those files are stale.

MIT — see [LICENSE](LICENSE).