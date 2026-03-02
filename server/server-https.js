/**
 * HTTPS dev server - iOS 센서 권한 필요 시 사용
 * npm run dev:https 실행 전에 npm run cert 생성 필요
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
  console.error('\n[HTTPS Server] 인증서 없음. 먼저 실행: npm run cert');
  console.error('  생성될 파일: certs/key.pem, certs/cert.pem\n');
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
  console.log(`Local:   https://localhost:${HTTP_PORT} (인증서 경고 무시 가능)`);
  console.log(`Network: https://${localIp}:${HTTP_PORT}`);
  console.log('\niOS 센서 권한: 모바일에서 위 Network URL로 접속');
  console.log('처음 접속 시 "연결이 비공개가 아닙니다" 경고 → 고급 → 계속\n');
});

process.on('SIGINT', () => {
  console.log('\n[x] Shutting down...');
  server.close();
  process.exit(0);
});
