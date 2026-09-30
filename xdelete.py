#!/usr/bin/env python3
"""Local X (Twitter) post cleanup via official API v2."""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import re
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

API_BASE = "https://api.x.com/2"
DEFAULT_CONFIG = Path("config.json")
DEFAULT_ENV = Path(".env")
DEFAULT_STATE = Path("state.json")

ENV_TO_CRED_KEY = {
    "X_API_KEY": "api_key",
    "X_API_SECRET": "api_secret",
    "X_ACCESS_TOKEN": "access_token",
    "X_ACCESS_TOKEN_SECRET": "access_token_secret",
}

DELETE_COST_USD = 0.010
READ_OWNED_COST_USD = 0.001


@dataclass
class Post:
    id: str
    text: str
    created_at: datetime
    like_count: int
    repost_count: int
    reply_count: int
    quote_count: int
    is_reply: bool
    is_repost: bool
    has_media: bool
    username: str | None = None

    def category(self) -> str:
        if self.is_repost:
            kind = "reposts"
        elif self.is_reply:
            kind = "replies"
        else:
            kind = "tweets"
        media = "media" if self.has_media else "text"
        return f"{kind}/{media}"

    def permalink(self) -> str:
        user = self.username or "i"
        return f"https://x.com/{user}/status/{self.id}"


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def strip_json_comments(text: str) -> str:
    result: list[str] = []
    i = 0
    while i < len(text):
        if text[i : i + 2] == "//":
            while i < len(text) and text[i] != "\n":
                i += 1
        elif text[i : i + 2] == "/*":
            i += 2
            while i < len(text) - 1 and text[i : i + 2] != "*/":
                i += 1
            i = min(i + 2, len(text))
        elif text[i] == '"':
            result.append(text[i])
            i += 1
            while i < len(text):
                ch = text[i]
                result.append(ch)
                if ch == "\\":
                    i += 1
                    if i < len(text):
                        result.append(text[i])
                        i += 1
                elif ch == '"':
                    i += 1
                    break
                else:
                    i += 1
        else:
            result.append(text[i])
            i += 1
    return "".join(result)


def load_config(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    return json.loads(strip_json_comments(text))


def load_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        values[key] = val
    return values


def load_credentials(env_path: Path) -> dict[str, str]:
    file_vars = load_env_file(env_path)
    creds: dict[str, str] = {}
    for env_name, cred_key in ENV_TO_CRED_KEY.items():
        value = os.environ.get(env_name) or file_vars.get(env_name) or ""
        creds[cred_key] = value.strip()
    return creds


def save_json(path: Path, data: dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def parse_rfc3339(s: str) -> datetime:
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s).astimezone(timezone.utc)


def format_rfc3339(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def percent_encode(s: str) -> str:
    return urllib.parse.quote(str(s), safe="~")


def oauth_signature(
    method: str,
    url: str,
    params: dict[str, str],
    consumer_secret: str,
    token_secret: str,
) -> str:
    sorted_params = "&".join(
        f"{percent_encode(k)}={percent_encode(v)}"
        for k, v in sorted(params.items())
    )
    base = "&".join(
        [
            percent_encode(method.upper()),
            percent_encode(url),
            percent_encode(sorted_params),
        ]
    )
    key = f"{percent_encode(consumer_secret)}&{percent_encode(token_secret)}"
    digest = hmac.new(key.encode(), base.encode(), hashlib.sha1).digest()
    return base64.b64encode(digest).decode()


def oauth_header(
    method: str,
    url: str,
    query: dict[str, str],
    creds: dict[str, str],
) -> str:
    oauth_params = {
        "oauth_consumer_key": creds["api_key"],
        "oauth_nonce": hashlib.sha256(os.urandom(32)).hexdigest()[:32],
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": str(int(time.time())),
        "oauth_token": creds["access_token"],
        "oauth_version": "1.0",
    }
    sign_params = {**query, **oauth_params}
    oauth_params["oauth_signature"] = oauth_signature(
        method,
        url,
        sign_params,
        creds["api_secret"],
        creds["access_token_secret"],
    )
    parts = [
        f'{percent_encode(k)}="{percent_encode(v)}"'
        for k, v in sorted(oauth_params.items())
    ]
    return "OAuth " + ", ".join(parts)


class XClient:
    def __init__(self, creds: dict[str, str]) -> None:
        self.creds = creds
        self._user_id: str | None = None
        self._username: str | None = None

    def request(
        self,
        method: str,
        path: str,
        query: dict[str, str] | None = None,
    ) -> tuple[int, dict[str, Any], dict[str, str]]:
        query = query or {}
        url = f"{API_BASE}{path}"
        if query:
            url = f"{url}?{urllib.parse.urlencode(query)}"
        base_url = f"{API_BASE}{path}"
        auth = oauth_header(method, base_url, query, self.creds)
        req = urllib.request.Request(url, method=method, headers={"Authorization": auth})
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                body = resp.read().decode()
                headers = {k.lower(): v for k, v in resp.headers.items()}
                data = json.loads(body) if body else {}
                return resp.status, data, headers
        except urllib.error.HTTPError as e:
            body = e.read().decode()
            headers = {k.lower(): v for k, v in e.headers.items()}
            try:
                data = json.loads(body) if body else {}
            except json.JSONDecodeError:
                data = {"raw": body}
            return e.code, data, headers

    def wait_rate_limit(self, headers: dict[str, str]) -> None:
        reset = headers.get("x-rate-limit-reset")
        if not reset:
            time.sleep(60)
            return
        wait = max(0, int(reset) - int(time.time()) + 1)
        if wait > 0:
            print(f"Rate limited; sleeping {wait}s...", file=sys.stderr)
            time.sleep(wait)

    def users_me(self) -> tuple[str, str]:
        if self._user_id and self._username:
            return self._user_id, self._username
        status, data, headers = self.request("GET", "/users/me")
        if status == 429:
            self.wait_rate_limit(headers)
            return self.users_me()
        if status != 200:
            raise RuntimeError(f"GET /users/me failed ({status}): {data}")
        user = data["data"]
        self._user_id = user["id"]
        self._username = user["username"]
        return self._user_id, self._username

    def fetch_user_posts(
        self,
        user_id: str,
        *,
        start_time: datetime | None,
        end_time: datetime,
        include_reposts: bool,
    ) -> list[Post]:
        posts: list[Post] = []
        pagination: str | None = None
        exclude = [] if include_reposts else ["retweets"]
        query_base: dict[str, str] = {
            "max_results": "100",
            "tweet.fields": "created_at,public_metrics,referenced_tweets,attachments",
            "expansions": "attachments.media_keys",
        }
        if exclude:
            query_base["exclude"] = ",".join(exclude)
        query_base["end_time"] = format_rfc3339(end_time)
        if start_time is not None:
            query_base["start_time"] = format_rfc3339(start_time)

        while True:
            query = dict(query_base)
            if pagination:
                query["pagination_token"] = pagination
            status, data, headers = self.request(
                "GET", f"/users/{user_id}/tweets", query
            )
            if status == 429:
                self.wait_rate_limit(headers)
                continue
            if status != 200:
                raise RuntimeError(
                    f"GET /users/{user_id}/tweets failed ({status}): {data}"
                )
            for item in data.get("data") or []:
                posts.append(parse_post(item, self._username))
            meta = data.get("meta") or {}
            pagination = meta.get("next_token")
            if not pagination:
                break
        return posts

    def delete_post(self, post_id: str) -> tuple[bool, int, dict[str, Any]]:
        status, data, headers = self.request("DELETE", f"/tweets/{post_id}")
        if status == 429:
            self.wait_rate_limit(headers)
            return self.delete_post(post_id)
        if status == 404:
            return True, status, data
        if status == 200:
            deleted = (data.get("data") or {}).get("deleted", True)
            return bool(deleted), status, data
        return False, status, data


def parse_post(item: dict[str, Any], username: str | None) -> Post:
    metrics = item.get("public_metrics") or {}
    refs = item.get("referenced_tweets") or []
    is_reply = any(r.get("type") == "replied_to" for r in refs)
    is_repost = any(r.get("type") == "retweeted" for r in refs)
    attachments = item.get("attachments") or {}
    media_keys = attachments.get("media_keys") or []
    return Post(
        id=str(item["id"]),
        text=item.get("text") or "",
        created_at=parse_rfc3339(item["created_at"]),
        like_count=int(metrics.get("like_count", 0)),
        repost_count=int(metrics.get("retweet_count", 0)),
        reply_count=int(metrics.get("reply_count", 0)),
        quote_count=int(metrics.get("quote_count", 0)),
        is_reply=is_reply,
        is_repost=is_repost,
        has_media=bool(media_keys),
        username=username,
    )


KINDS = ("tweets", "replies", "reposts")
MEDIA_VARIANTS = ("text", "media")


def rules_for_bucket(bucket: Any) -> list[dict[str, Any]] | None:
    if bucket is None:
        return None
    if not isinstance(bucket, dict):
        raise ValueError("each category bucket must be an object or null")
    if bucket.get("enabled") is False:
        return None
    rules = bucket.get("rules", [])
    if rules is None:
        return None
    if not isinstance(rules, list):
        raise ValueError("'rules' must be a list")
    return rules


def iter_config_rules(
    config: dict[str, Any],
) -> list[tuple[str, list[dict[str, Any]]]]:
    out: list[tuple[str, list[dict[str, Any]]]] = []
    for kind in KINDS:
        section = config.get(kind) or {}
        if not isinstance(section, dict):
            raise ValueError(f"'{kind}' must be an object")
        for variant in MEDIA_VARIANTS:
            rules = rules_for_bucket(section.get(variant))
            if rules:
                out.append((f"{kind}/{variant}", rules))
    return out


def validate_config(config: dict[str, Any]) -> None:
    grouped = iter_config_rules(config)
    if not grouped:
        raise ValueError(
            "config must define at least one category with non-empty 'rules'"
        )
    min_age = config.get("min_age_days", 1)
    for label, rules in grouped:
        for i, rule in enumerate(rules):
            if "older_than_days" not in rule:
                raise ValueError(f"{label} rules[{i}] missing older_than_days")
            if rule["older_than_days"] < min_age:
                raise ValueError(
                    f"{label} rules[{i}] older_than_days must be >= "
                    f"min_age_days ({min_age})"
                )


def rules_for_post(
    post: Post, config: dict[str, Any]
) -> list[dict[str, Any]]:
    kind, variant = post.category().split("/", 1)
    section = config.get(kind) or {}
    rules = rules_for_bucket(section.get(variant))
    return rules or []


def rule_matches(post: Post, rule: dict[str, Any], now: datetime) -> bool:
    age_days = (now - post.created_at).total_seconds() / 86400
    if age_days < rule["older_than_days"]:
        return False
    if "max_likes" in rule and post.like_count >= rule["max_likes"]:
        return False
    if "max_reposts" in rule and post.repost_count >= rule["max_reposts"]:
        return False
    if "max_replies" in rule and post.reply_count >= rule["max_replies"]:
        return False
    if "max_quotes" in rule and post.quote_count >= rule["max_quotes"]:
        return False
    return True


def first_matching_rule(
    post: Post, rules: list[dict[str, Any]], now: datetime
) -> dict[str, Any] | None:
    for rule in rules:
        if rule_matches(post, rule, now):
            return rule
    return None


def match_post(
    post: Post, config: dict[str, Any], now: datetime
) -> tuple[str, dict[str, Any]] | None:
    rules = rules_for_post(post, config)
    if not rules:
        return None
    matched = first_matching_rule(post, rules, now)
    if not matched:
        return None
    return post.category(), matched


def rule_label(rule: dict[str, Any]) -> str:
    parts = [f"older_than_days={rule['older_than_days']}"]
    for key in ("max_likes", "max_reposts", "max_replies", "max_quotes"):
        if key in rule:
            parts.append(f"{key}={rule[key]}")
    return ", ".join(parts)


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"last_fetch_at": None, "queue": []}
    return load_json(path)


def queue_entry(post: Post, category: str, rule: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": post.id,
        "text": post.text[:200],
        "category": category,
        "created_at": format_rfc3339(post.created_at),
        "like_count": post.like_count,
        "repost_count": post.repost_count,
        "reply_count": post.reply_count,
        "quote_count": post.quote_count,
        "matched_rule": rule,
        "queued_at": format_rfc3339(datetime.now(timezone.utc)),
    }


def merge_queue(
    existing: list[dict[str, Any]], new_entries: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    by_id = {e["id"]: e for e in existing}
    for e in new_entries:
        by_id[e["id"]] = e
    return sorted(by_id.values(), key=lambda x: x["created_at"])


def collect_candidates(
    client: XClient,
    config: dict[str, Any],
    state: dict[str, Any],
    now: datetime,
) -> tuple[list[tuple[Post, str, dict[str, Any]]], int]:
    user_id, _ = client.users_me()
    grouped = iter_config_rules(config)
    fetch_rules: list[dict[str, Any]] = []
    for _label, rules in grouped:
        fetch_rules.extend(rules)
    last_fetch = state.get("last_fetch_at")
    last_dt = parse_rfc3339(last_fetch) if last_fetch else None
    include_reposts = any(label.startswith("reposts/") for label, _ in grouped)

    seen_ids: set[str] = set()
    all_posts: list[Post] = []
    for rule in fetch_rules:
        end_time = now - timedelta(days=rule["older_than_days"])
        start_time = None
        if last_dt is not None:
            start_time = last_dt - timedelta(days=rule["older_than_days"])
        batch = client.fetch_user_posts(
            user_id,
            start_time=start_time,
            end_time=end_time,
            include_reposts=include_reposts,
        )
        for p in batch:
            if p.id not in seen_ids:
                seen_ids.add(p.id)
                all_posts.append(p)

    matches: list[tuple[Post, str, dict[str, Any]]] = []
    for post in all_posts:
        hit = match_post(post, config, now)
        if hit:
            matches.append((post, hit[0], hit[1]))
    return matches, len(all_posts)


def cmd_preview(
    config_path: Path,
    env_path: Path,
    state_path: Path,
    *,
    update_state: bool,
) -> int:
    config = load_config(config_path)
    validate_config(config)
    creds = load_credentials(env_path)
    for env_name, cred_key in ENV_TO_CRED_KEY.items():
        if not creds.get(cred_key):
            print(f"missing {env_name} (set in {env_path} or environment)", file=sys.stderr)
            return 1

    state = load_state(state_path)
    client = XClient(creds)
    now = datetime.now(timezone.utc)

    try:
        matches, read_count = collect_candidates(client, config, state, now)
    except RuntimeError as e:
        print(e, file=sys.stderr)
        return 1

    print(f"Read {read_count} posts (~${read_count * READ_OWNED_COST_USD:.3f} at owned-read rates)")
    print(f"Matched {len(matches)} posts for deletion")
    est = len(matches) * DELETE_COST_USD
    print(f"Estimated delete cost if all applied: ${est:.2f}\n")

    for post, category, rule in matches:
        snippet = re.sub(r"\s+", " ", post.text)[:80]
        print(
            f"{post.created_at.date()}  {category}  likes={post.like_count}  "
            f"reposts={post.repost_count}  rule=[{rule_label(rule)}]"
        )
        print(f"  {post.permalink()}")
        print(f"  {snippet!r}\n")

    if update_state:
        new_queue = merge_queue(
            state.get("queue") or [],
            [queue_entry(p, c, r) for p, c, r in matches],
        )
        state["queue"] = new_queue
        state["last_fetch_at"] = format_rfc3339(now)
        save_json(state_path, state)
        print(f"Updated {state_path} (queue size: {len(new_queue)})")

    return 0


def cmd_delete(
    config_path: Path,
    env_path: Path,
    state_path: Path,
    *,
    apply: bool,
) -> int:
    config = load_config(config_path)
    validate_config(config)
    creds = load_credentials(env_path)
    for env_name, cred_key in ENV_TO_CRED_KEY.items():
        if not creds.get(cred_key):
            print(f"missing {env_name} (set in {env_path} or environment)", file=sys.stderr)
            return 1
    state = load_state(state_path)
    queue = state.get("queue") or []
    cap = int(config.get("max_deletes_per_run", 50))

    if not queue:
        print("Queue is empty. Run preview with --update-state first.")
        return 0

    pending = queue[:cap]
    print(f"{len(pending)} posts to delete (cap {cap}, {len(queue)} in queue)")

    if not apply:
        for e in pending:
            print(f"  would delete {e['id']}  {e.get('text', '')[:60]}")
        print("\nPass --apply to perform deletions.")
        return 0

    client = XClient(creds)
    remaining = list(queue)
    deleted = 0
    for entry in pending:
        post_id = entry["id"]
        ok, status, data = client.delete_post(post_id)
        if ok:
            deleted += 1
            remaining = [e for e in remaining if e["id"] != post_id]
            print(f"deleted {post_id}")
        else:
            print(f"failed {post_id} ({status}): {data}", file=sys.stderr)
            break

    state["queue"] = remaining
    save_json(state_path, state)
    print(f"Deleted {deleted}; {len(remaining)} left in queue")
    return 0 if deleted == len(pending) or deleted > 0 else 1


def cmd_self_check() -> int:
    now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    post = Post(
        id="1",
        text="hello",
        created_at=datetime(2026, 4, 1, 12, 0, tzinfo=timezone.utc),
        like_count=3,
        repost_count=0,
        reply_count=0,
        quote_count=0,
        is_reply=False,
        is_repost=False,
        has_media=False,
    )
    rule = {"older_than_days": 30, "max_likes": 5}
    assert rule_matches(post, rule, now)
    assert post.category() == "tweets/text"
    post2 = Post(
        id="2",
        text="popular",
        created_at=datetime(2026, 4, 1, 12, 0, tzinfo=timezone.utc),
        like_count=10,
        repost_count=0,
        reply_count=0,
        quote_count=0,
        is_reply=False,
        is_repost=False,
        has_media=False,
    )
    assert not rule_matches(post2, rule, now)
    cfg = {
        "min_age_days": 1,
        "tweets": {"text": {"rules": [rule]}, "media": {"rules": []}},
        "replies": {"text": None, "media": None},
        "reposts": {"text": None, "media": None},
    }
    assert match_post(post, cfg, now) == ("tweets/text", rule)
    assert match_post(post2, cfg, now) is None
    reply = Post(
        id="3",
        text="reply",
        created_at=post.created_at,
        like_count=0,
        repost_count=0,
        reply_count=0,
        quote_count=0,
        is_reply=True,
        is_repost=False,
        has_media=False,
    )
    assert match_post(reply, cfg, now) is None
    sample = strip_json_comments('{"a": 1 // comment\n}')
    assert json.loads(sample) == {"a": 1}
    with tempfile.NamedTemporaryFile("w", suffix=".env", delete=False) as f:
        f.write("# comment\nX_API_KEY=abc\nexport X_API_SECRET='sec ret'\n")
        tmp_path = Path(f.name)
    loaded = load_env_file(tmp_path)
    tmp_path.unlink(missing_ok=True)
    assert loaded.get("X_API_KEY") == "abc"
    assert loaded.get("X_API_SECRET") == "sec ret"
    print("self-check ok")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Local X post cleanup")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument(
        "--env",
        type=Path,
        default=DEFAULT_ENV,
        help="Path to .env file with X API OAuth 1.0a credentials",
    )
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    sub = parser.add_subparsers(dest="command", required=True)

    p_preview = sub.add_parser("preview", help="List posts that match rules")
    p_preview.add_argument(
        "--update-state",
        action="store_true",
        help="Advance fetch watermark and merge matches into deletion queue",
    )

    p_delete = sub.add_parser("delete", help="Delete queued posts")
    p_delete.add_argument(
        "--apply",
        action="store_true",
        help="Actually delete (default is dry-run of queue head)",
    )

    sub.add_parser("self-check", help="Run offline matcher tests")

    args = parser.parse_args()
    if args.command == "preview":
        return cmd_preview(
            args.config,
            args.env,
            args.state,
            update_state=args.update_state,
        )
    if args.command == "delete":
        return cmd_delete(
            args.config,
            args.env,
            args.state,
            apply=args.apply,
        )
    if args.command == "self-check":
        return cmd_self_check()
    return 1


if __name__ == "__main__":
    sys.exit(main())
