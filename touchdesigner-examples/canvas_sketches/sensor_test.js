// W2TD Canvas Sketch — Sensor Test
// ==================================
// 모션·오리엔테이션·터치 센서를 시각적으로 확인하는 테스트 스케치.
//
// ── 센서 → 시각 효과 ──────────────────────────────────────────────
//   ax, ay   : 가속도 → 공 위치 관성 (반대 방향으로 밀림)
//   az       : 수직 가속도 → 공 크기 (위로 들면 작아짐, 내리면 커짐)
//   ob, og   : 오리엔테이션 → Holofoil 무지개 광택 (기울기에 따라 색/반사 변화)
//   touch    : 터치 → 심장박동 크기 애니메이션 (GSAP tween)
//
// ── TD에서 전송 방법 ──────────────────────────────────────────────
//   op('web_server_dat').module.send_canvas_code_to_all(
//       op('web_server_dat'), op('sensor_test_dat')
//   )
//
// ── 필요한 전역 (index.html에서 로드됨) ──────────────────────────
//   gsap       — 심장박동 tween
//   canvas     — CanvasRunner이 주입하는 #render-canvas 엘리먼트
//   requestFrame — CanvasRunner 래핑된 rAF
//   getSensors — W2TD 센서 스냅샷 함수

(function () {
  'use strict';
  const ctx = canvas.getContext('2d');

  // ── Physics state ───────────────────────────────────────────────
  const pos = { x: 0, y: 0 };        // center offset (canvas px)
  const vel = { x: 0, y: 0 };        // velocity (px/s)
  let scaleOffset = 0;                // z-axis scale shift
  let scaleVel    = 0;

  // ── Heartbeat (GSAP tween target) ──────────────────────────────
  const heart  = { s: 1.0 };         // heart.s = heartbeat scale multiplier
  let heartBusy = false;
  let prevTouch = 0;

  // ── Tuning constants ────────────────────────────────────────────
  const SPRING        = 8.0;   // spring force toward center
  const DAMPING       = 5.5;   // velocity damping coefficient (exp decay)
  const ACCEL_XY      = 20.0;  // accelerometer → position sensitivity
  const ACCEL_Z       = 5.0;   // accelerometer z → scale sensitivity
  const MAX_OFF_RATIO = 0.28;  // max displacement as fraction of base radius
  const BASE_R_RATIO  = 0.22;  // base radius as fraction of min(W, H)

  let lastTs = 0;

  // ── Heartbeat trigger ────────────────────────────────────────────
  // 커졌다 → 오버슈트 수축 → 탄성 복귀
  // GSAP elastic ease가 마지막 "탱탱한 복귀" 느낌을 자연스럽게 처리해 줌
  function triggerHeartbeat() {
    if (heartBusy) return;
    heartBusy = true;
    // 1. 빠르게 부풀음
    gsap.to(heart, {
      s: 1.30,
      duration: 0.20,
      ease: 'power3.out',
      onComplete: function () {
        // 2. 오버슈트 수축
        gsap.to(heart, {
          s: 0.91,
          duration: 0.16,
          ease: 'power2.in',
          onComplete: function () {
            // 3. 탄성 복귀 (elastic.out: 약간 튕기며 원래 크기로)
            gsap.to(heart, {
              s: 1.0,
              duration: 0.42,
              ease: 'elastic.out(1.15, 0.55)',
              onComplete: function () { heartBusy = false; }
            });
          }
        });
      }
    });
  }

  // ── Holofoil rendering (CodePen PrQKgo 스타일) ────────────────────
  // ob = orientation beta  (전후 기울기, 0°=수평, 90°=직립)
  // og = orientation gamma (좌우 기울기, -90~+90°)
  //
  // CodePen 핵심 기법 재현:
  //   1. 좁은 무지개 빛줄기 (::before) — 기울기로 위치 이동
  //   2. 홀로그래픽 미세 줄무늬 (::after holo.png 대체)
  //   3. 반짝이 sparkle (::after sparkles.gif 대체)
  //   4. color-dodge 블렌드로 강렬한 발광

  // sparkle 텍스처 캐시 (한 번만 생성)
  let _sparkleCanvas = null;
  function _getSparkleTexture(size) {
    if (_sparkleCanvas && _sparkleCanvas.width === size) return _sparkleCanvas;
    _sparkleCanvas = document.createElement('canvas');
    _sparkleCanvas.width = size;
    _sparkleCanvas.height = size;
    const sctx = _sparkleCanvas.getContext('2d');
    // 랜덤 sparkle 점 생성
    for (let i = 0; i < size * size * 0.012; i++) {
      const sx = Math.random() * size;
      const sy = Math.random() * size;
      const sr = 0.5 + Math.random() * 1.5;
      const sa = 0.3 + Math.random() * 0.7;
      sctx.fillStyle = `rgba(255, 255, 255, ${sa})`;
      sctx.beginPath();
      sctx.arc(sx, sy, sr, 0, Math.PI * 2);
      sctx.fill();
    }
    return _sparkleCanvas;
  }

  // 홀로그래픽 줄무늬 텍스처 캐시
  let _holoCanvas = null;
  function _getHoloTexture(size) {
    if (_holoCanvas && _holoCanvas.width === size) return _holoCanvas;
    _holoCanvas = document.createElement('canvas');
    _holoCanvas.width = size;
    _holoCanvas.height = size;
    const hctx = _holoCanvas.getContext('2d');
    // 미세한 가로 줄무늬 — 회절격자(diffraction grating) 효과
    const lineH = 3;
    for (let y = 0; y < size; y += lineH) {
      const hue = (y / size) * 360;
      hctx.fillStyle = `hsla(${hue}, 100%, 50%, 0.12)`;
      hctx.fillRect(0, y, size, lineH * 0.6);
    }
    return _holoCanvas;
  }

  function drawHolofoil(cx, cy, r, ob, og) {
    ctx.save();

    // ── 원형 클리핑 ──────────────────────────────────────────────
    ctx.beginPath();
    ctx.arc(cx, cy, r, 0, Math.PI * 2);
    ctx.clip();

    const x0 = cx - r, y0 = cy - r, d = r * 2;

    // ── 어두운 금속 베이스 ────────────────────────────────────────
    ctx.fillStyle = '#040712';
    ctx.fillRect(x0, y0, d, d);

    // ── 기울기 정규화 ────────────────────────────────────────────
    // 감도 높게: ±45°에서 풀 스윙
    const tiltX = Math.max(-1, Math.min(1, og / 45));
    const tiltY = Math.max(-1, Math.min(1, (ob - 90) / 45));
    // CodePen의 px, py (0~100 퍼센트) 에 대응
    const px = 50 + tiltX * 40;
    const py = 50 + tiltY * 40;

    // ── Layer 1: 좁은 무지개 빛줄기 (::before 재현) ──────────────
    // CodePen: linear-gradient(110deg, transparent 25%, color1 48%, color2 52%, transparent 75%)
    // 기울기에 따라 빛줄기 위치와 각도가 이동
    const sweepAngle = Math.PI * 0.6 + tiltX * 0.5;
    const sa = Math.cos(sweepAngle), sb = Math.sin(sweepAngle);
    const g1 = ctx.createLinearGradient(
      cx - sa * r * 1.3, cy - sb * r * 1.3,
      cx + sa * r * 1.3, cy + sb * r * 1.3
    );
    // 빛줄기 중심 위치 — 기울기로 이동
    const bandCenter = 0.2 + (px / 100) * 0.6;   // 0.2 ~ 0.8 범위
    const bw = 0.04;  // 매우 좁은 밴드
    const hueA = ((180 + tiltX * 60 + tiltY * 40) % 360 + 360) % 360;
    const hueB = ((hueA + 40) % 360);

    g1.addColorStop(0, 'transparent');
    g1.addColorStop(Math.max(0.01, bandCenter - bw * 4), 'transparent');
    g1.addColorStop(Math.max(0.02, bandCenter - bw), `hsla(${hueA}, 100%, 65%, 0.85)`);
    g1.addColorStop(bandCenter, 'rgba(255, 255, 255, 0.95)');
    g1.addColorStop(Math.min(0.98, bandCenter + bw), `hsla(${hueB}, 100%, 65%, 0.85)`);
    g1.addColorStop(Math.min(0.99, bandCenter + bw * 4), 'transparent');
    g1.addColorStop(1, 'transparent');

    // CodePen: filter brightness(0.66) contrast(1.33), opacity 0.88
    ctx.globalCompositeOperation = 'color-dodge';
    ctx.globalAlpha = 0.88;
    ctx.fillStyle = g1;
    ctx.fillRect(x0, y0, d, d);
    ctx.globalAlpha = 1;

    // ── Layer 2: 홀로그래픽 무지개 워시 (::after 베이스 그라디언트) ─
    // CodePen: linear-gradient(125deg, #ff008450 15%, ... #cc4cfa50 85%)
    const hueShift = tiltX * 100 + tiltY * 70;
    const g2 = ctx.createLinearGradient(
      cx - r * 0.9, cy - r * 0.9,
      cx + r * 0.9, cy + r * 0.9
    );
    const colors = [
      [0.00, 330], [0.15, 30], [0.30, 60], [0.45, 120],
      [0.60, 180], [0.75, 240], [0.90, 280], [1.00, 330]
    ];
    colors.forEach(function (pair) {
      var stop = pair[0], h = pair[1];
      var hue = ((h + hueShift) % 360 + 360) % 360;
      g2.addColorStop(stop, 'hsla(' + hue + ', 90%, 55%, 0.25)');
    });
    ctx.globalCompositeOperation = 'color-dodge';
    ctx.fillStyle = g2;
    ctx.fillRect(x0, y0, d, d);

    // ── Layer 3: 홀로그래픽 줄무늬 텍스처 (holo.png 대체) ────────
    // 줄무늬가 기울기에 따라 스크롤되는 효과
    var texSize = Math.max(64, Math.round(r * 2));
    var holoTex = _getHoloTexture(texSize);
    ctx.save();
    ctx.globalCompositeOperation = 'color-dodge';
    ctx.globalAlpha = 0.75;
    // 기울기에 따라 텍스처 오프셋
    var texOffX = tiltX * texSize * 0.3;
    var texOffY = tiltY * texSize * 0.4;
    ctx.translate(cx, cy);
    ctx.rotate(sweepAngle * 0.3);
    ctx.drawImage(holoTex, -r + texOffX, -r + texOffY, d, d);
    ctx.restore();

    // ── Layer 4: sparkle 반짝이 (sparkles.gif 대체) ──────────────
    // 위치가 기울기에 따라 미세하게 이동 → 반짝이는 효과
    var sparkTex = _getSparkleTexture(texSize);
    ctx.save();
    ctx.globalCompositeOperation = 'color-dodge';
    // opacity: CodePen처럼 기울기 각도에 비례
    var pa = Math.abs(50 - px) + Math.abs(50 - py);
    var sparkOpacity = Math.min(1, 0.3 + pa * 0.02);
    ctx.globalAlpha = sparkOpacity;
    var spkOffX = (px - 50) * r * 0.014;
    var spkOffY = (py - 50) * r * 0.014;
    ctx.drawImage(sparkTex, x0 + spkOffX, y0 + spkOffY, d, d);
    ctx.restore();

    // ── Layer 5: specular highlight ──────────────────────────────
    // 기울기에 따라 밝은 반사점이 이동
    var specX = cx + tiltX * r * 0.5;
    var specY = cy - tiltY * r * 0.45;
    var sg = ctx.createRadialGradient(specX, specY, 0, specX, specY, r * 0.55);
    sg.addColorStop(0,    'rgba(255, 255, 255, 0.9)');
    sg.addColorStop(0.06, 'rgba(255, 255, 255, 0.55)');
    sg.addColorStop(0.20, 'rgba(255, 255, 255, 0.12)');
    sg.addColorStop(1,    'rgba(255, 255, 255, 0)');
    ctx.globalCompositeOperation = 'color-dodge';
    ctx.fillStyle = sg;
    ctx.fillRect(x0, y0, d, d);

    // ── Edge vignette (구체감) ────────────────────────────────────
    var vg = ctx.createRadialGradient(cx, cy, r * 0.45, cx, cy, r);
    vg.addColorStop(0, 'rgba(0, 0, 0, 0)');
    vg.addColorStop(0.7, 'rgba(0, 0, 0, 0.15)');
    vg.addColorStop(1, 'rgba(0, 0, 0, 0.65)');
    ctx.globalCompositeOperation = 'source-over';
    ctx.fillStyle = vg;
    ctx.fillRect(x0, y0, d, d);

    ctx.restore();
  }

  // ── Main loop ────────────────────────────────────────────────────
  function loop(ts) {
    const dt = Math.min((ts - lastTs) / 1000, 0.05);  // cap at 50ms
    lastTs = ts;

    const s  = getSensors();
    const W  = canvas.width;
    const H  = canvas.height;
    const baseR = Math.min(W, H) * BASE_R_RATIO;

    // ── Position physics (ax, ay) ──────────────────────────────
    // 폰이 오른쪽으로 가속 → 공은 관성으로 왼쪽으로 밀림 (-ax)
    vel.x += (-s.ax * ACCEL_XY - SPRING * pos.x) * dt;
    vel.y += ( s.ay * ACCEL_XY - SPRING * pos.y) * dt;

    const damp = Math.exp(-DAMPING * dt);
    vel.x *= damp;
    vel.y *= damp;

    pos.x += vel.x * dt;
    pos.y += vel.y * dt;

    // 최대 이동 반경 제한
    const dist = Math.sqrt(pos.x * pos.x + pos.y * pos.y);
    const maxOff = baseR * MAX_OFF_RATIO;
    if (dist > maxOff) {
      const ratio = maxOff / dist;
      pos.x *= ratio;
      pos.y *= ratio;
    }

    // ── Scale physics (az) ──────────────────────────────────────
    // 위로 들면 az 양수 → scaleOffset 감소 → 공 작아짐
    scaleVel += (-s.az * ACCEL_Z - SPRING * scaleOffset) * dt;
    scaleVel *= damp;
    scaleOffset += scaleVel * dt;
    scaleOffset = Math.max(-0.30, Math.min(0.50, scaleOffset));

    // ── Touch → heartbeat ───────────────────────────────────────
    const tc = s.touch_count || 0;
    if (tc > 0 && prevTouch === 0) triggerHeartbeat();
    prevTouch = tc;

    // ── Final values ────────────────────────────────────────────
    const finalScale = (1.0 + scaleOffset) * heart.s;
    const r  = baseR * Math.max(0.25, finalScale);
    const cx = W / 2 + pos.x;
    const cy = H / 2 + pos.y;

    // ── Render ──────────────────────────────────────────────────
    ctx.clearRect(0, 0, W, H);

    // 배경 (어두운 색으로 holofoil 색감 살림)
    ctx.fillStyle = '#111118';
    ctx.fillRect(0, 0, W, H);

    // 그림자 — displacement 반대 방향으로 약간 오프셋
    ctx.save();
    ctx.shadowColor   = 'rgba(0, 0, 0, 0.6)';
    ctx.shadowBlur    = r * 0.45;
    ctx.shadowOffsetX = -pos.x * 0.12 + 3;
    ctx.shadowOffsetY =  pos.y * 0.12 + 5;
    ctx.beginPath();
    ctx.arc(cx, cy, r * 0.92, 0, Math.PI * 2);
    ctx.fillStyle = '#000';
    ctx.fill();
    ctx.restore();

    // Holofoil 공
    drawHolofoil(cx, cy, r, s.ob || 0, s.og || 0);

    requestFrame(loop);
  }

  // ── Start ────────────────────────────────────────────────────────
  requestFrame(function (ts) {
    lastTs = ts;
    requestFrame(loop);
  });

  // ── Cleanup (CanvasRunner이 stop/reload 시 호출) ─────────────────
  return function cleanup() {
    gsap.killTweensOf(heart);
  };

})();
