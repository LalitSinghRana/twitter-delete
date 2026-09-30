'use strict';

const LS_KEY = 'twitterdelete_settings';
const LEGACY_LS_KEY = 'xdelete_settings';
const DEFAULTS = {
  older_than_days: 30,
  max_likes: 5,
  max_deletes_per_run: 50,
  delay_ms: 3000,
};

function parseCompactCount(raw) {
  if (raw == null || raw === '') return 0;
  const s = String(raw).replace(/,/g, '').trim();
  const m = s.match(/^([\d.]+)\s*([KMBkmb])?$/);
  if (!m) return 0;
  let n = parseFloat(m[1]);
  const u = (m[2] || '').toLowerCase();
  if (u === 'k') n *= 1e3;
  else if (u === 'm') n *= 1e6;
  else if (u === 'b') n *= 1e9;
  return Math.round(n);
}

function ageInDays(createdAt, now) {
  const t = createdAt instanceof Date ? createdAt.getTime() : new Date(createdAt).getTime();
  return (now.getTime() - t) / 86400000;
}

function parseOlderThanDays(raw, fallback) {
  const n = parseFloat(String(raw).trim());
  if (!Number.isFinite(n) || n <= 0) return fallback;
  return n;
}

function postMatches(createdAt, likeCount, olderThanDays, maxLikes, now) {
  if (!(olderThanDays > 0) || !(maxLikes > 0)) return false;
  if (ageInDays(createdAt, now) < olderThanDays) return false;
  if (likeCount >= maxLikes) return false;
  return true;
}

function loadSettings() {
  try {
    let raw = localStorage.getItem(LS_KEY);
    if (!raw) raw = localStorage.getItem(LEGACY_LS_KEY);
    if (!raw) return { ...DEFAULTS };
    return { ...DEFAULTS, ...JSON.parse(raw) };
  } catch {
    return { ...DEFAULTS };
  }
}

function saveSettings(s) {
  localStorage.setItem(LS_KEY, JSON.stringify(s));
}

function runSelfCheck() {
  const now = new Date('2026-06-01T12:00:00Z');
  const old = new Date('2026-04-01T12:00:00Z');
  if (!postMatches(old, 3, 30, 5, now)) throw new Error('expected match');
  if (postMatches(old, 10, 30, 5, now)) throw new Error('expected no match (likes)');
  if (postMatches(new Date('2026-05-20T12:00:00Z'), 0, 30, 5, now)) {
    throw new Error('expected no match (age)');
  }
  if (parseCompactCount('1.2K') !== 1200) throw new Error('parseCompactCount');
  const halfDayAgo = new Date(now.getTime() - 13 * 3600000);
  if (!postMatches(halfDayAgo, 0, 0.5, 5, now)) throw new Error('expected match at 0.5 days');
  const recent = new Date(now.getTime() - 6 * 3600000);
  if (postMatches(recent, 0, 0.5, 5, now)) throw new Error('expected no match under 0.5 days');
  if (parseOlderThanDays('0.5', 30) !== 0.5) throw new Error('parseOlderThanDays');
  console.log('self-check ok');
}

if (typeof process !== 'undefined' && process.argv[1]?.includes('twitter-delete.js')) {
  runSelfCheck();
  process.exit(0);
}

(function twitterDeleteBookmarklet() {
  if (typeof document === 'undefined') return;

  const host = location.hostname;
  if (!host.endsWith('x.com') && !host.endsWith('twitter.com')) {
    alert('Open x.com (Twitter), go to your profile, then click the bookmark again.');
    return;
  }

  if (document.getElementById('twitterdelete-panel')) {
    document.getElementById('twitterdelete-panel').style.display = 'block';
    return;
  }

  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  window.twitterdeleteStop = false;

  const panel = document.createElement('div');
  panel.id = 'twitterdelete-panel';
  panel.style.cssText =
    'position:fixed;z-index:999999;top:12px;right:12px;width:360px;max-height:85vh;' +
    'overflow:auto;background:#15202b;color:#e7e9ea;border:1px solid #38444d;' +
    'border-radius:12px;padding:14px;font:13px/1.4 system-ui,sans-serif;' +
    'box-shadow:0 8px 32px rgba(0,0,0,.45)';

  panel.innerHTML = `
    <div style="font-weight:600;font-size:15px;margin-bottom:10px">twitter-delete</div>
    <label style="display:block;margin:6px 0">Older than (days, decimals OK — 0.5 = 12h)
      <input id="td-days" type="number" min="0.01" step="0.1" style="width:100%;margin-top:4px;padding:6px;background:#192734;border:1px solid #38444d;color:inherit;border-radius:6px">
    </label>
    <label style="display:block;margin:6px 0">Fewer than (likes)
      <input id="td-likes" type="number" min="1" style="width:100%;margin-top:4px;padding:6px;background:#192734;border:1px solid #38444d;color:inherit;border-radius:6px">
    </label>
    <label style="display:block;margin:6px 0">Max deletes this run
      <input id="td-cap" type="number" min="1" style="width:100%;margin-top:4px;padding:6px;background:#192734;border:1px solid #38444d;color:inherit;border-radius:6px">
    </label>
    <div style="display:flex;gap:8px;margin:10px 0;flex-wrap:wrap">
      <button type="button" id="td-scan" style="flex:1;padding:8px;background:#1d9bf0;color:#fff;border:none;border-radius:999px;cursor:pointer">Scan</button>
      <button type="button" id="td-stop" style="padding:8px 12px;background:#38444d;color:#fff;border:none;border-radius:999px;cursor:pointer">Stop</button>
    </div>
    <div id="td-status" style="margin-bottom:8px;color:#71767b;min-height:1.2em"></div>
    <div id="td-list"></div>
    <button type="button" id="td-delete" disabled style="width:100%;margin-top:10px;padding:10px;background:#f4212e;color:#fff;border:none;border-radius:999px;cursor:pointer;opacity:.5">Delete selected</button>
  `;
  document.body.appendChild(panel);

  const elDays = panel.querySelector('#td-days');
  const elLikes = panel.querySelector('#td-likes');
  const elCap = panel.querySelector('#td-cap');
  const elStatus = panel.querySelector('#td-status');
  const elList = panel.querySelector('#td-list');
  const btnScan = panel.querySelector('#td-scan');
  const btnStop = panel.querySelector('#td-stop');
  const btnDelete = panel.querySelector('#td-delete');

  const settings = loadSettings();
  elDays.value = settings.older_than_days;
  elLikes.value = settings.max_likes;
  elCap.value = settings.max_deletes_per_run;

  let matches = [];

  function readSettingsFromPanel() {
    const s = {
      older_than_days: parseOlderThanDays(elDays.value, DEFAULTS.older_than_days),
      max_likes: Math.max(1, parseInt(elLikes.value, 10) || DEFAULTS.max_likes),
      max_deletes_per_run: Math.max(1, parseInt(elCap.value, 10) || DEFAULTS.max_deletes_per_run),
      delay_ms: DEFAULTS.delay_ms,
    };
    saveSettings(s);
    return s;
  }

  function setStatus(msg) {
    elStatus.textContent = msg;
  }

  function ownHandle() {
    const navHref = document.querySelector('a[data-testid="AppTabBar_Profile_Link"]')?.getAttribute('href') || '';
    const fromNav = navHref.match(/^\/([A-Za-z0-9_]{1,15})$/);
    if (fromNav) return fromNav[1];
    const switcher = document.querySelector('[data-testid="SideNav_AccountSwitcher_Button"]')?.textContent || '';
    const fromSw = switcher.match(/@([A-Za-z0-9_]{1,15})/);
    return fromSw ? fromSw[1] : null;
  }

  function onOwnProfile() {
    const RESERVED = ['home', 'explore', 'notifications', 'messages', 'i', 'search', 'settings', 'compose'];
    const TABS = ['with_replies', 'media', 'likes', 'highlights'];
    const m = location.pathname.match(/^\/([A-Za-z0-9_]{1,15})(?:\/([A-Za-z0-9_]+))?\/?$/);
    if (!m || RESERVED.includes(m[1].toLowerCase())) return null;
    if (m[2] && !TABS.includes(m[2].toLowerCase())) return null;
    return m[1];
  }

  function likeCountFromArticle(article) {
    const btn = article.querySelector('[data-testid="like"], [data-testid="unlike"]');
    const label = btn?.getAttribute('aria-label') || '';
    const num = label.match(/([\d,.]+[KMBkmb]?)/);
    return parseCompactCount(num ? num[1] : '0');
  }

  function parseStatusPath(href) {
    const m = (href || '').match(/^\/([^/]+)\/status\/(\d+)/);
    return m ? { author: m[1], id: m[2] } : null;
  }

  function authorFromUserName(article) {
    const block = article.querySelector('[data-testid="User-Name"]');
    if (!block) return null;
    for (const a of block.querySelectorAll('a[href^="/"]')) {
      const m = (a.getAttribute('href') || '').match(/^\/([A-Za-z0-9_]{1,15})$/);
      if (m) return m[1];
    }
    return null;
  }

  function extractFromArticle(article, profileUser) {
    const profile = profileUser.toLowerCase();
    const social = article.querySelector('[data-testid="socialContext"]')?.textContent || '';
    if (/pinned/i.test(social)) return null;

    const isRetweet = /reposted/i.test(social);
    const isMyRetweet = !!article.querySelector('[data-testid="unretweet"]');
    const displayAuthor = authorFromUserName(article);

    const statusCandidates = [];
    for (const a of article.querySelectorAll('a[href*="/status/"]')) {
      const parsed = parseStatusPath(a.getAttribute('href'));
      if (parsed) statusCandidates.push({ link: a, ...parsed });
    }
    if (!statusCandidates.length) return null;

    let pick =
      (displayAuthor &&
        statusCandidates.find((c) => c.author.toLowerCase() === displayAuthor.toLowerCase())) ||
      statusCandidates.find((c) => c.author.toLowerCase() === profile) ||
      (isRetweet || isMyRetweet ? statusCandidates[0] : null);
    if (!pick) return null;

    const isMine = displayAuthor
      ? displayAuthor.toLowerCase() === profile
      : pick.author.toLowerCase() === profile;
    if (!isMine && !isMyRetweet && !isRetweet) return null;

    const author = isMine ? displayAuthor || pick.author : pick.author;
    const id = pick.id;
    const timeEl = pick.link.querySelector('time') || article.querySelector('time');
    const ts = timeEl?.getAttribute('datetime');
    if (!ts) return null;

    const text = article.querySelector('[data-testid="tweetText"]')?.textContent || '';
    const likes = likeCountFromArticle(article);

    return {
      id,
      author,
      createdAt: ts,
      likes,
      text: text.slice(0, 120),
      url: `https://x.com/${author}/status/${id}`,
      isRetweet: isMyRetweet || isRetweet,
    };
  }

  function renderList() {
    elList.innerHTML = '';
    if (!matches.length) {
      btnDelete.disabled = true;
      btnDelete.style.opacity = '0.5';
      return;
    }
    btnDelete.disabled = false;
    btnDelete.style.opacity = '1';
    matches.forEach((item, idx) => {
      const row = document.createElement('label');
      row.style.cssText = 'display:block;padding:8px 0;border-bottom:1px solid #38444d;cursor:pointer';
      row.innerHTML = `
        <input type="checkbox" data-idx="${idx}" checked style="margin-right:8px">
        <span>${item.createdAt.slice(0, 10)} · ♥${item.likes}</span><br>
        <span style="color:#71767b;font-size:12px">${item.text.replace(/</g, '&lt;')}</span>
      `;
      elList.appendChild(row);
    });
  }

  async function scan() {
    window.twitterdeleteStop = false;
    const cfg = readSettingsFromPanel();
    const me = ownHandle();
    const pathUser = onOwnProfile();
    if (!me || !pathUser || me.toLowerCase() !== pathUser.toLowerCase()) {
      setStatus(me ? `Open https://x.com/${me}/with_replies first.` : 'Could not detect your account.');
      return;
    }

    matches = [];
    renderList();
    btnScan.disabled = true;
    setStatus('Scanning…');

    const seen = new Set();
    const now = new Date();
    const maxScrolls = 40;
    const scrollDelay = 2500;

    for (let s = 0; s < maxScrolls && !window.twitterdeleteStop; s++) {
      const articles = document.querySelectorAll('article[data-testid="tweet"]');
      for (const article of articles) {
        const item = extractFromArticle(article, me);
        if (!item || seen.has(item.id)) continue;
        seen.add(item.id);
        if (postMatches(item.createdAt, item.likes, cfg.older_than_days, cfg.max_likes, now)) {
          matches.push(item);
        }
      }
      setStatus(`Scanning… ${seen.size} read, ${matches.length} match`);
      window.scrollTo(0, document.body.scrollHeight);
      await sleep(scrollDelay);
    }

    renderList();
    btnScan.disabled = false;
    setStatus(window.twitterdeleteStop ? 'Scan stopped.' : `Done. ${matches.length} match(es).`);
  }

  function findArticleById(id) {
    for (const article of document.querySelectorAll('article[data-testid="tweet"]')) {
      const link = article.querySelector('a[href*="/status/"]');
      if (link?.getAttribute('href')?.includes(`/status/${id}`)) return article;
    }
    return null;
  }

  async function deleteOne(article, isRetweet) {
    const caret = article.querySelector('[data-testid="caret"]');
    if (!caret) return false;
    caret.scrollIntoView({ block: 'center' });
    await sleep(400);
    caret.click();
    await sleep(1200);

    let action = null;
    for (const item of document.querySelectorAll('[role="menuitem"]')) {
      const t = item.textContent.toLowerCase();
      if (isRetweet && t.includes('undo repost')) {
        action = item;
        break;
      }
      if (!isRetweet && t.includes('delete')) {
        action = item;
        break;
      }
    }
    if (!action) {
      document.body.click();
      await sleep(400);
      return false;
    }
    action.click();
    await sleep(1200);
    const confirm = document.querySelector('[data-testid="confirmationSheetConfirm"]');
    if (confirm) {
      confirm.click();
      await sleep(800);
      return true;
    }
    document.body.click();
    return false;
  }

  async function deleteSelected() {
    const cfg = readSettingsFromPanel();
    const checked = [...elList.querySelectorAll('input[type=checkbox]:checked')].map((cb) =>
      matches[parseInt(cb.getAttribute('data-idx'), 10)]
    ).filter(Boolean);

    if (!checked.length) {
      setStatus('Nothing selected.');
      return;
    }
    const cap = Math.min(checked.length, cfg.max_deletes_per_run);
    const msg = `Permanently delete ${cap} post(s)? This cannot be undone.`;
    if (!confirm(msg)) return;

    window.twitterdeleteStop = false;
    btnDelete.disabled = true;
    let deleted = 0;

    for (let i = 0; i < cap && !window.twitterdeleteStop; i++) {
      const item = checked[i];
      let article = findArticleById(item.id);
      if (!article) {
        setStatus(`Scroll to load post ${item.id}…`);
        window.scrollTo(0, document.body.scrollHeight);
        await sleep(2000);
        article = findArticleById(item.id);
      }
      if (!article) {
        setStatus(`Could not find post ${item.id} on page.`);
        break;
      }
      const ok = await deleteOne(article, item.isRetweet);
      if (ok) {
        deleted++;
        matches = matches.filter((m) => m.id !== item.id);
        renderList();
        setStatus(`Deleted ${deleted}/${cap}…`);
      } else {
        setStatus('Delete menu failed. Stopping.');
        break;
      }
      await sleep(cfg.delay_ms);
    }

    btnDelete.disabled = matches.length === 0;
    btnDelete.style.opacity = matches.length ? '1' : '0.5';
    setStatus(`Finished. Deleted ${deleted}.`);
  }

  btnScan.addEventListener('click', () => scan());
  btnStop.addEventListener('click', () => {
    window.twitterdeleteStop = true;
    setStatus('Stopping…');
  });
  btnDelete.addEventListener('click', () => deleteSelected());
})();
