#!/usr/bin/env node
'use strict';

const fs = require('fs');
const path = require('path');

const root = __dirname;
let src = fs.readFileSync(path.join(root, 'twitter-delete.js'), 'utf8');

src = src.replace(/function runSelfCheck\(\) \{[\s\S]*?\n\}\n\n/, '');
src = src.replace(
  /if \(typeof process !== 'undefined' && process\.argv\[1\]\?\.includes\('twitter-delete\.js'\)\) \{[\s\S]*?process\.exit\(0\);\n\}/,
  ''
);

const href = 'javascript:' + encodeURIComponent(src.trim());

const htmlPath = path.join(root, 'bookmarklet.html');
let html = fs.readFileSync(htmlPath, 'utf8');
const safeHref = href.replace(/"/g, '&quot;');
html = html.replace(
  /<a class="bookmark" id="twitterdelete-bookmark" href="[^"]*"[^>]*>[^<]*<\/a>/,
  `<a class="bookmark" id="twitterdelete-bookmark" href="${safeHref}">twitter-delete</a>`
);
fs.writeFileSync(htmlPath, html);
fs.writeFileSync(path.join(root, 'bookmarklet.url.txt'), href + '\n');
console.log('Updated bookmarklet.html and bookmarklet.url.txt (' + href.length + ' chars)');
