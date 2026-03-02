/**
 * HTTPS dev server - required for iOS sensor permissions
 * Run npm run cert before npm run dev:https
 */
const https = require('https');
const fs = require('fs');
const path = require('path');

const HTTP_PORT = parseInt(process.env.PORT) || 3000;
const PUBLIC_DIR = path.join(__dirname, '..', 'docs');
const CERTS_DIR = path.join(__dirname, '..', 'certs');

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

function createHandler() {
  return (req, res) => {
    let filePath = path.join(PUBLIC_DIR, req.url === '/' ? 'index.html' : req.url);
    filePath = path.normalize(filePath);

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
  };
}

const keyPath = path.join(CERTS_DIR, 'key.pem');
const certPath = path.join(CERTS_DIR, 'cert.pem');

if (!fs.existsSync(keyPath) || !fs.existsSync(certPath)) {
  console.error('\n[HTTPS Server] No certificate. Run first: npm run cert');
  console.error('  Will create: certs/key.pem, certs/cert.pem\n');
  process.exit(1);
}

const options = {
  key: fs.readFileSync(keyPath),
  cert: fs.readFileSync(certPath),
};

const server = https.createServer(options, createHandler());

server.listen(HTTP_PORT, () => {
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

  console.log('\n=== W2TD Dev Server (HTTPS) ===');
  console.log(`Local:   https://localhost:${HTTP_PORT} (certificate warning can be ignored)`);
  console.log(`Network: https://${localIp}:${HTTP_PORT}`);
  console.log('\niOS sensor permission: access above Network URL from mobile');
  console.log('First visit: "Connection not private" warning → Advanced → Proceed\n');
});

process.on('SIGINT', () => {
  console.log('\n[x] Shutting down...');
  server.close();
  process.exit(0);
});
