const http = require('http');
const fs = require('fs');
const path = require('path');

// Configuration
const HTTP_PORT = parseInt(process.env.PORT) || 3000;
const PUBLIC_DIR = path.join(__dirname, '..', 'docs');

const MIME_TYPES = {
  '.html': 'text/html',
  '.css': 'text/css',
  '.js': 'application/javascript',
  '.json': 'application/json',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.svg': 'image/svg+xml',
  '.ico': 'image/x-icon',
};

const httpServer = http.createServer((req, res) => {
  let filePath = path.join(PUBLIC_DIR, req.url === '/' ? 'index.html' : req.url);
  filePath = path.normalize(filePath);

  // Security: prevent directory traversal
  if (!filePath.startsWith(PUBLIC_DIR)) {
    res.writeHead(403);
    res.end('Forbidden');
    return;
  }

  const ext = path.extname(filePath);
  const contentType = MIME_TYPES[ext] || 'application/octet-stream';

  fs.readFile(filePath, (err, data) => {
    if (err) {
      res.writeHead(404);
      res.end('Not Found');
      return;
    }
    res.writeHead(200, { 'Content-Type': contentType });
    res.end(data);
  });
});

httpServer.listen(HTTP_PORT, () => {
  const networkInterfaces = require('os').networkInterfaces();
  let localIp = 'localhost';
  for (const iface of Object.values(networkInterfaces)) {
    for (const info of iface) {
      if (info.family === 'IPv4' && !info.internal) {
        localIp = info.address;
        break;
      }
    }
  }

  console.log(`\n=== W2TD Dev Server ===`);
  console.log(`Local:   http://localhost:${HTTP_PORT}`);
  console.log(`Network: http://${localIp}:${HTTP_PORT}`);
  console.log(`\nAccess from mobile using the Network URL.`);
  console.log(`Enter the TouchDesigner WebSocket DAT address to connect.\n`);
});

process.on('SIGINT', () => {
  console.log('\n[x] Shutting down...');
  httpServer.close();
  process.exit(0);
});
