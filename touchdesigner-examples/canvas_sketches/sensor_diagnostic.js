// W2TD Canvas Sketch — Sensor Diagnostic
// ========================================
// THREE.js 기반 3D 디바이스 모델 + 2D HUD 오버레이.
// 모든 센서를 시각적으로 확인할 수 있는 진단 도구.
//
// ── 시각화 구성 ──────────────────────────────────────────────────
//   3D Scene:
//     - 폰 모델: orientation(alpha, beta, gamma) → 실시간 회전
//     - 가속도 화살표: accelerometer → 힘의 방향/크기
//     - 자이로 링 3개: gyroscope → 각 축 회전 속도
//     - 폰 스크린: 터치 포인트 실시간 표시
//   2D HUD:
//     - 상단: Accel/Gyro 값 + 스파크라인
//     - 하단: Orientation 값 + Touch/GPS 상태
//
// ── TD에서 전송 ──────────────────────────────────────────────────
//   op('web_server_dat').module.send_canvas_code_to_all(
//       op('web_server_dat'), op('sensor_diagnostic_dat')
//   )
//
// ── 필요 전역 (index.html) ──────────────────────────────────────
//   THREE, gsap, canvas, requestFrame, getSensors

(function () {
  'use strict';

  const dpr = window.devicePixelRatio || 1;
  const W = canvas.width;
  const H = canvas.height;
  const cssW = W / dpr;
  const cssH = H / dpr;

  // ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  //  THREE.js — offscreen WebGL canvas
  // ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  const gl = document.createElement('canvas');
  gl.width = W;
  gl.height = H;

  const renderer = new THREE.WebGLRenderer({ canvas: gl, antialias: true });
  renderer.setSize(cssW, cssH, false);
  renderer.setPixelRatio(dpr);
  renderer.setClearColor(0x06060c);
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.1;

  const scene = new THREE.Scene();

  const camera = new THREE.PerspectiveCamera(42, cssW / cssH, 0.1, 100);
  camera.position.set(0, 2.8, 6);
  camera.lookAt(0, 0.2, 0);

  // ── Lights ────────────────────────────────────────────────────
  scene.add(new THREE.AmbientLight(0x1a1a2e, 0.8));

  const key = new THREE.DirectionalLight(0x4488ff, 2.5);
  key.position.set(3, 5, 4);
  scene.add(key);

  const fill = new THREE.PointLight(0xff4466, 1.0, 18);
  fill.position.set(-4, 3, -2);
  scene.add(fill);

  const rim = new THREE.PointLight(0x44ffaa, 0.6, 12);
  rim.position.set(0, -1, -5);
  scene.add(rim);

  // ── Grid Floor ────────────────────────────────────────────────
  const grid = new THREE.GridHelper(14, 28, 0x1a1a33, 0x0d0d1a);
  grid.position.y = -2.8;
  scene.add(grid);

  // ── Phone Model ───────────────────────────────────────────────
  const PW = 1.0, PH = 2.0, PD = 0.1;
  const phoneGeo = new THREE.BoxGeometry(PW, PH, PD);
  const phoneMat = new THREE.MeshPhysicalMaterial({
    color: 0x1a1a2e,
    metalness: 0.85,
    roughness: 0.15,
    clearcoat: 1.0,
    clearcoatRoughness: 0.08,
  });
  const phone = new THREE.Mesh(phoneGeo, phoneMat);
  scene.add(phone);

  // Phone screen — dynamic CanvasTexture for touch visualization
  const scrCanvas = document.createElement('canvas');
  scrCanvas.width = 256;
  scrCanvas.height = 512;
  const scrTex = new THREE.CanvasTexture(scrCanvas);
  scrTex.minFilter = THREE.LinearFilter;
  const scrGeo = new THREE.PlaneGeometry(PW * 0.88, PH * 0.92);
  const scrMat = new THREE.MeshBasicMaterial({ map: scrTex });
  const scrMesh = new THREE.Mesh(scrGeo, scrMat);
  scrMesh.position.z = PD / 2 + 0.001;
  phone.add(scrMesh);

  // Camera lens (back)
  const lensGeo = new THREE.CircleGeometry(0.07, 16);
  const lensMat = new THREE.MeshPhysicalMaterial({
    color: 0x080808, metalness: 1.0, roughness: 0.0, clearcoat: 1.0,
  });
  const lens = new THREE.Mesh(lensGeo, lensMat);
  lens.position.set(-0.25, 0.72, -PD / 2 - 0.001);
  lens.rotation.y = Math.PI;
  phone.add(lens);

  // ── Accel Arrow ───────────────────────────────────────────────
  const arrowDir = new THREE.Vector3(0, -1, 0);
  const arrow = new THREE.ArrowHelper(arrowDir, new THREE.Vector3(0, 0, 0), 1.5, 0x44dd88, 0.18, 0.09);
  arrow.visible = false;
  phone.add(arrow);

  // ── Gyro Rings ────────────────────────────────────────────────
  const ringGeo = new THREE.TorusGeometry(1.55, 0.015, 8, 64);
  const ringColors = [0xff4466, 0x44dd88, 0x4488ff];
  const rings = ringColors.map((c, i) => {
    const mat = new THREE.MeshBasicMaterial({
      color: c, transparent: true, opacity: 0.25, side: THREE.DoubleSide,
    });
    const ring = new THREE.Mesh(ringGeo, mat);
    // Initial orientations: X, Y, Z planes
    if (i === 0) ring.rotation.x = Math.PI / 2;   // XZ plane (alpha)
    if (i === 2) ring.rotation.y = Math.PI / 2;   // YZ plane (gamma)
    scene.add(ring);
    return ring;
  });

  // ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  //  2D HUD — composited on top of 3D
  // ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  const ctx = canvas.getContext('2d');

  const HIST = 90;
  const hist = {};
  ['ax', 'ay', 'az', 'ga', 'gb', 'gg'].forEach(k => hist[k] = []);
  function push(k, v) { const a = hist[k]; a.push(v); if (a.length > HIST) a.shift(); }

  // ── Sparkline ─────────────────────────────────────────────────
  function sparkline(data, color, x, y, w, h, min, max) {
    if (data.length < 2) return;
    ctx.save();
    ctx.strokeStyle = color;
    ctx.lineWidth = 1.5 * dpr;
    ctx.globalAlpha = 0.75;
    ctx.lineJoin = 'round';
    ctx.beginPath();
    for (let i = 0; i < data.length; i++) {
      const px = x + (i / (HIST - 1)) * w;
      const norm = Math.max(0, Math.min(1, (data[i] - min) / (max - min || 1)));
      const py = y + h - norm * h;
      i === 0 ? ctx.moveTo(px, py) : ctx.lineTo(px, py);
    }
    ctx.stroke();
    ctx.restore();
  }

  // ── Panel bg ──────────────────────────────────────────────────
  function panelBg(y, h) {
    ctx.fillStyle = 'rgba(6, 6, 12, 0.8)';
    ctx.fillRect(0, y, W, h);
    ctx.strokeStyle = 'rgba(68, 136, 255, 0.15)';
    ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(0, y + h); ctx.lineTo(W, y + h); ctx.stroke();
  }

  // ── Status dot ────────────────────────────────────────────────
  function statusDot(x, y, active, label) {
    ctx.fillStyle = active ? '#44dd88' : '#333';
    ctx.beginPath(); ctx.arc(x, y, 3.5 * dpr, 0, Math.PI * 2); ctx.fill();
    ctx.fillStyle = active ? '#aaa' : '#555';
    ctx.font = `${9 * dpr}px -apple-system, sans-serif`;
    ctx.textAlign = 'left';
    ctx.fillText(label, x + 7 * dpr, y + 3 * dpr);
  }

  // ── HUD Draw ──────────────────────────────────────────────────
  function drawHUD(s) {
    const p = 14 * dpr;
    const fs = 11 * dpr;
    const vs = 14 * dpr;
    const headFont = `600 ${fs}px -apple-system, sans-serif`;
    const valFont = `700 ${vs}px 'SF Mono', 'Fira Code', monospace`;

    // ─── TOP: Accel + Gyro ──────────────────────────────────────
    const topH = 105 * dpr;
    panelBg(0, topH);

    const halfW = W / 2;
    const colW = halfW / 3 - p;

    // Accel
    ctx.fillStyle = '#666';
    ctx.font = headFont;
    ctx.textAlign = 'left';
    ctx.fillText('ACCELEROMETER  m/s²', p, 16 * dpr);

    const accel = [
      { l: 'X', v: s.ax, c: '#ff4466' },
      { l: 'Y', v: s.ay, c: '#44dd88' },
      { l: 'Z', v: s.az, c: '#4488ff' },
    ];
    accel.forEach((a, i) => {
      ctx.fillStyle = a.c;
      ctx.font = valFont;
      ctx.fillText(a.l + ':' + a.v.toFixed(1), p + i * colW, 38 * dpr);
    });

    const spY = 48 * dpr, spH = 48 * dpr, spW = halfW - p * 2;
    // Zero line
    ctx.strokeStyle = 'rgba(255,255,255,0.05)';
    ctx.beginPath(); ctx.moveTo(p, spY + spH / 2); ctx.lineTo(p + spW, spY + spH / 2); ctx.stroke();
    sparkline(hist.ax, '#ff4466', p, spY, spW, spH, -20, 20);
    sparkline(hist.ay, '#44dd88', p, spY, spW, spH, -20, 20);
    sparkline(hist.az, '#4488ff', p, spY, spW, spH, -20, 20);

    // Gyro
    const gx = halfW + p;
    ctx.fillStyle = '#666';
    ctx.font = headFont;
    ctx.fillText('GYROSCOPE  °/s', gx, 16 * dpr);

    const gyro = [
      { l: 'α', v: s.ga, c: '#ff4466' },
      { l: 'β', v: s.gb, c: '#44dd88' },
      { l: 'γ', v: s.gg, c: '#4488ff' },
    ];
    gyro.forEach((g, i) => {
      ctx.fillStyle = g.c;
      ctx.font = valFont;
      ctx.fillText(g.l + ':' + g.v.toFixed(1), gx + i * colW, 38 * dpr);
    });

    ctx.strokeStyle = 'rgba(255,255,255,0.05)';
    ctx.beginPath(); ctx.moveTo(gx, spY + spH / 2); ctx.lineTo(gx + spW, spY + spH / 2); ctx.stroke();
    sparkline(hist.ga, '#ff4466', gx, spY, spW, spH, -250, 250);
    sparkline(hist.gb, '#44dd88', gx, spY, spW, spH, -250, 250);
    sparkline(hist.gg, '#4488ff', gx, spY, spW, spH, -250, 250);

    // ─── BOTTOM: Orientation + Touch + GPS ──────────────────────
    const btmH = 85 * dpr;
    const btmY = H - btmH;
    ctx.fillStyle = 'rgba(6, 6, 12, 0.8)';
    ctx.fillRect(0, btmY, W, btmH);
    ctx.strokeStyle = 'rgba(68, 136, 255, 0.15)';
    ctx.beginPath(); ctx.moveTo(0, btmY); ctx.lineTo(W, btmY); ctx.stroke();

    // Orientation
    ctx.fillStyle = '#666';
    ctx.font = headFont;
    ctx.fillText('ORIENTATION', p, btmY + 16 * dpr);

    const orient = [
      { l: 'α', v: s.oa, c: '#ffaa44', u: '°' },
      { l: 'β', v: s.ob, c: '#4488ff', u: '°' },
      { l: 'γ', v: s.og, c: '#aa66ff', u: '°' },
    ];
    orient.forEach((o, i) => {
      ctx.fillStyle = o.c;
      ctx.font = valFont;
      ctx.fillText(o.l + ':' + o.v.toFixed(1) + o.u, p + i * (colW + 4 * dpr), btmY + 38 * dpr);
    });

    // Compass mini (alpha heading)
    const compR = 20 * dpr;
    const compCx = p + 3 * (colW + 4 * dpr) + compR + 10 * dpr;
    const compCy = btmY + 30 * dpr;
    ctx.strokeStyle = 'rgba(255,255,255,0.12)';
    ctx.lineWidth = 1.5 * dpr;
    ctx.beginPath(); ctx.arc(compCx, compCy, compR, 0, Math.PI * 2); ctx.stroke();
    // Needle
    const needleA = -(s.oa || 0) * Math.PI / 180;
    ctx.save();
    ctx.translate(compCx, compCy);
    ctx.rotate(needleA);
    ctx.fillStyle = '#ff4466';
    ctx.beginPath();
    ctx.moveTo(0, -compR * 0.7);
    ctx.lineTo(-3 * dpr, compR * 0.3);
    ctx.lineTo(3 * dpr, compR * 0.3);
    ctx.closePath();
    ctx.fill();
    ctx.fillStyle = '#fff';
    ctx.beginPath(); ctx.arc(0, 0, 2 * dpr, 0, Math.PI * 2); ctx.fill();
    ctx.restore();
    // N label
    const nx = compCx + Math.sin(needleA) * (compR + 8 * dpr);
    const ny = compCy - Math.cos(needleA) * (compR + 8 * dpr);
    ctx.fillStyle = '#ff4466';
    ctx.font = `bold ${9 * dpr}px sans-serif`;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText('N', nx, ny);

    // Touch + GPS (right half)
    ctx.fillStyle = '#666';
    ctx.font = headFont;
    ctx.textAlign = 'left';
    ctx.textBaseline = 'alphabetic';
    const tc = s.touch_count || 0;
    ctx.fillText('TOUCH', gx, btmY + 16 * dpr);
    ctx.fillStyle = tc > 0 ? '#44dd88' : '#444';
    ctx.font = valFont;
    ctx.fillText(tc + ' finger' + (tc !== 1 ? 's' : ''), gx, btmY + 38 * dpr);

    // Touch coords
    if (tc > 0) {
      const ts = 10 * dpr;
      ctx.font = `${ts}px 'SF Mono', monospace`;
      ctx.fillStyle = '#888';
      let tStr = '';
      for (let i = 0; i < Math.min(tc, 5); i++) {
        const tx = s['t' + i + 'x'], ty = s['t' + i + 'y'];
        if (tx != null) tStr += `#${i + 1}(${tx.toFixed(2)},${ty.toFixed(2)}) `;
      }
      ctx.fillText(tStr.trim(), gx, btmY + 55 * dpr);
    }

    // GPS
    if (s.lat !== 0 || s.lon !== 0) {
      ctx.fillStyle = '#44dd88';
      ctx.font = `${10 * dpr}px 'SF Mono', monospace`;
      ctx.fillText('GPS: ' + s.lat.toFixed(5) + ', ' + s.lon.toFixed(5), gx, btmY + 72 * dpr);
    }

    // Status dots
    const dotX = W - 70 * dpr;
    const hasMotion = Math.abs(s.ax) > 0.05 || Math.abs(s.ay) > 0.05;
    const hasOrient = Math.abs(s.oa) > 0.05 || Math.abs(s.ob) > 0.05;
    statusDot(dotX, btmY + 14 * dpr, hasMotion, 'Motion');
    statusDot(dotX, btmY + 30 * dpr, hasOrient, 'Orient');
    statusDot(dotX, btmY + 46 * dpr, tc > 0, 'Touch');
    statusDot(dotX, btmY + 62 * dpr, s.lat !== 0, 'GPS');

    // ─── CENTER LABEL ───────────────────────────────────────────
    ctx.fillStyle = 'rgba(255,255,255,0.06)';
    ctx.font = `700 ${18 * dpr}px -apple-system, sans-serif`;
    ctx.textAlign = 'center';
    ctx.fillText('SENSOR DIAGNOSTIC', W / 2, topH + 28 * dpr);
  }

  // ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  //  Phone Screen Texture (touch points on the 3D model)
  // ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  const TOUCH_COLORS = ['#ff4466', '#44dd88', '#4488ff', '#ffaa44', '#ff44aa'];

  function updateScreen(s) {
    const sc = scrCanvas.getContext('2d');
    const sw = scrCanvas.width, sh = scrCanvas.height;

    sc.fillStyle = '#08080f';
    sc.fillRect(0, 0, sw, sh);

    // Subtle grid
    sc.strokeStyle = 'rgba(68, 136, 255, 0.08)';
    sc.lineWidth = 0.5;
    for (let i = 0; i <= 8; i++) {
      const gy = (i / 8) * sh;
      sc.beginPath(); sc.moveTo(0, gy); sc.lineTo(sw, gy); sc.stroke();
      const gx = (i / 8) * sw;
      sc.beginPath(); sc.moveTo(gx, 0); sc.lineTo(gx, sh); sc.stroke();
    }

    const tc = s.touch_count || 0;
    for (let i = 0; i < tc; i++) {
      const tx = s['t' + i + 'x'], ty = s['t' + i + 'y'];
      if (tx == null) continue;
      const px = tx * sw, py = ty * sh;
      const col = TOUCH_COLORS[i % TOUCH_COLORS.length];

      // Glow
      const grd = sc.createRadialGradient(px, py, 0, px, py, 28);
      grd.addColorStop(0, col + '66');
      grd.addColorStop(1, col + '00');
      sc.fillStyle = grd;
      sc.beginPath(); sc.arc(px, py, 28, 0, Math.PI * 2); sc.fill();

      // Dot
      sc.fillStyle = col;
      sc.beginPath(); sc.arc(px, py, 5, 0, Math.PI * 2); sc.fill();

      // Crosshair
      sc.strokeStyle = col + '44';
      sc.lineWidth = 0.5;
      sc.beginPath(); sc.moveTo(px, 0); sc.lineTo(px, sh); sc.stroke();
      sc.beginPath(); sc.moveTo(0, py); sc.lineTo(sw, py); sc.stroke();
    }

    // Header text
    sc.fillStyle = 'rgba(255,255,255,0.15)';
    sc.font = '11px monospace';
    sc.textAlign = 'center';
    sc.fillText('TOUCH × ' + tc, sw / 2, 14);

    // Accel bar at bottom
    const barH = 6;
    const mag = Math.sqrt((s.ax || 0) ** 2 + (s.ay || 0) ** 2 + (s.az || 0) ** 2);
    const barW = Math.min(sw, (mag / 20) * sw);
    sc.fillStyle = '#44dd8866';
    sc.fillRect((sw - barW) / 2, sh - barH - 4, barW, barH);
    sc.fillStyle = 'rgba(255,255,255,0.12)';
    sc.font = '9px monospace';
    sc.fillText('|G| = ' + mag.toFixed(1), sw / 2, sh - barH - 8);

    scrTex.needsUpdate = true;
  }

  // ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  //  MAIN LOOP
  // ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  const smooth = { oa: 0, ob: 0, og: 0 };
  const ringVel = [0, 0, 0];
  let lastTs = 0;

  function loop(ts) {
    const dt = Math.min((ts - (lastTs || ts)) / 1000, 0.05);
    lastTs = ts;
    const s = getSensors();

    // History
    push('ax', s.ax); push('ay', s.ay); push('az', s.az);
    push('ga', s.ga); push('gb', s.gb); push('gg', s.gg);

    // ── Smooth orientation for 3D ──────────────────────────────
    const lf = 1 - Math.exp(-10 * dt);
    smooth.oa += ((s.oa || 0) - smooth.oa) * lf;
    smooth.ob += ((s.ob || 0) - smooth.ob) * lf;
    smooth.og += ((s.og || 0) - smooth.og) * lf;

    // Phone rotation (ZXY Euler for device orientation)
    const a = smooth.oa * Math.PI / 180;
    const b = smooth.ob * Math.PI / 180;
    const g = smooth.og * Math.PI / 180;

    // Reset and apply in correct order
    const euler = new THREE.Euler(b, a, -g, 'YXZ');
    phone.setRotationFromEuler(euler);

    // ── Accel arrow (in phone local space) ─────────────────────
    const ax = s.ax || 0, ay = s.ay || 0, az = s.az || 0;
    const mag = Math.sqrt(ax * ax + ay * ay + az * az);
    if (mag > 0.5) {
      const dir = new THREE.Vector3(ax, ay, az).normalize();
      arrow.setDirection(dir);
      arrow.setLength(Math.min(mag / 9.8 * 2.0, 3.0), 0.18, 0.09);
      arrow.visible = true;
    } else {
      arrow.visible = false;
    }

    // ── Gyro rings ─────────────────────────────────────────────
    const gyroScale = 0.0008;
    ringVel[0] += ((s.ga || 0) * gyroScale - ringVel[0]) * 0.1;
    ringVel[1] += ((s.gb || 0) * gyroScale - ringVel[1]) * 0.1;
    ringVel[2] += ((s.gg || 0) * gyroScale - ringVel[2]) * 0.1;
    rings[0].rotation.z += ringVel[0];
    rings[1].rotation.z += ringVel[1];
    rings[2].rotation.z += ringVel[2];

    // Ring opacity based on gyro activity
    const gyroMag = Math.abs(s.ga || 0) + Math.abs(s.gb || 0) + Math.abs(s.gg || 0);
    const baseOp = 0.08;
    const boostOp = Math.min(0.5, baseOp + gyroMag * 0.002);
    rings.forEach(r => { r.material.opacity = boostOp; });

    // ── Phone screen texture ───────────────────────────────────
    updateScreen(s);

    // ── Render 3D ──────────────────────────────────────────────
    renderer.render(scene, camera);

    // ── Composite onto main canvas ─────────────────────────────
    ctx.drawImage(gl, 0, 0, W, H);

    // ── 2D HUD overlay ─────────────────────────────────────────
    drawHUD(s);

    requestFrame(loop);
  }

  requestFrame(function (ts) {
    lastTs = ts;
    requestFrame(loop);
  });

  // ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  //  CLEANUP
  // ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  return function cleanup() {
    renderer.dispose();
    [phoneGeo, scrGeo, lensGeo, ringGeo].forEach(g => g.dispose());
    [phoneMat, scrMat, lensMat].forEach(m => m.dispose());
    rings.forEach(r => r.material.dispose());
    scrTex.dispose();
  };

})();
