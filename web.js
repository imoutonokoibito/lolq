'use strict';
// Public assets only. League access and user configurations never live on this server.
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const socket = process.env.SOCKET_PATH || '/var/run/imoutosuki/lolq.sock';
const root = path.join(__dirname, 'static');
const files = { '/': ['index.html', 'text/html; charset=utf-8'], '/index.html': ['index.html', 'text/html; charset=utf-8'],
  '/app.js': ['app.js', 'text/javascript; charset=utf-8'], '/connection.js': ['connection.js', 'text/javascript; charset=utf-8'],
  '/style.css': ['style.css', 'text/css; charset=utf-8'], '/release.json': ['release.json', 'application/json'] };
const csp = "default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; style-src 'self' 'unsafe-inline'; img-src 'self' data: https://ddragon.leagueoflegends.com https://raw.communitydragon.org; connect-src 'self' http://127.0.0.1:17653 https://ddragon.leagueoflegends.com https://raw.communitydragon.org; object-src 'none'; base-uri 'self'; frame-ancestors 'self'";
const server = http.createServer((req, res) => {
  if (!['GET', 'HEAD'].includes(req.method)) { res.writeHead(405); return res.end(); }
  const pathname = new URL(req.url, 'http://localhost').pathname;
  if (pathname === '/lolq') { res.writeHead(302, { Location: '/lolq/' }); return res.end(); }
  const relative = pathname.replace(/^\/lolq(?=\/)/, '');
  let file, type;
  if (relative === '/downloads/LoLQ-Setup.exe' || relative === '/downloads/SHA256SUMS.txt') {
    file = path.join(__dirname, 'downloads', path.basename(relative));
    type = relative.endsWith('.exe') ? 'application/octet-stream' : 'text/plain';
    res.setHeader('Content-Disposition', `attachment; filename="${path.basename(relative)}"`);
  } else if (files[relative]) {
    [file, type] = files[relative]; file = path.join(root, file);
  } else { res.writeHead(404); return res.end('Not found'); }
  fs.stat(file, (error, stat) => {
    if (error || !stat.isFile()) { res.writeHead(503, { 'Retry-After': '60' }); return res.end('Download temporarily unavailable. Please try again shortly.'); }
    res.writeHead(200, { 'Content-Type': type, 'Content-Length': stat.size,
      'Content-Security-Policy': csp, 'X-Content-Type-Options': 'nosniff', 'Referrer-Policy': 'no-referrer',
      'Cache-Control': 'no-cache' });
    if (req.method === 'HEAD') return res.end();
    const stream = fs.createReadStream(file);
    stream.on('error', () => res.destroy());
    res.on('close', () => stream.destroy());
    stream.pipe(res);
  });
});
if (process.env.PORT) server.listen(Number(process.env.PORT), '127.0.0.1');
else { if (fs.existsSync(socket)) fs.unlinkSync(socket); server.listen(socket, () => fs.chmodSync(socket, 0o660)); }
