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

  // ── Holofoil rendering ───────────────────────────────────────────
  // ob = orientation beta  (전후 기울기, 0°=수평, 90°=직립)
  // og = orientation gamma (좌우 기울기, -90~+90°)
  function drawHolofoil(cx, cy, r, ob, og) {
    ctx.save();

    // circle clip
    ctx.beginPath();
    ctx.arc(cx, cy, r, 0, Math.PI * 2);
    ctx.clip();

    // 어두운 금속 베이스
    ctx.fillStyle = '#07070f';
    ctx.fillRect(cx - r, cy - r, r * 2, r * 2);

    // 기울기에서 hue 기준값 산출
    // 폰을 들고 있을 때 ob≈90이므로 (ob-90)으로 정규화
    const tiltX = og  / 90;           // -1 ~ +1 (좌우)
    const tiltY = (ob - 90) / 90;     // -1 ~ +1 (전후, 0=직립)
    const hueBase = tiltX * 120 + tiltY * 80;

    // Rainbow layer 1 — gamma 기울기 방향을 그라디언트 축으로
    const angle1 = tiltX * (Math.PI / 2.5);
    const c1 = Math.cos(angle1), s1 = Math.sin(angle1);
    const g1 = ctx.createLinearGradient(
      cx + c1 * r, cy + s1 * r,
      cx - c1 * r, cy - s1 * r
    );
    for (let i = 0; i <= 6; i++) {
      const hue = ((hueBase + i * 60) % 360 + 360) % 360;
      g1.addColorStop(i / 6, `hsla(${hue.toFixed(0)}, 100%, 62%, 0.9)`);
    }
    ctx.globalCompositeOperation = 'screen';
    ctx.fillStyle = g1;
    ctx.fillRect(cx - r, cy - r, r * 2, r * 2);

    // Rainbow layer 2 — 수직 교차축 (회절 격자 느낌)
    const angle2 = angle1 + Math.PI / 2;
    const c2 = Math.cos(angle2), s2 = Math.sin(angle2);
    const g2 = ctx.createLinearGradient(
      cx + c2 * r * 0.9, cy + s2 * r * 0.9,
      cx - c2 * r * 0.9, cy - s2 * r * 0.9
    );
    for (let i = 0; i <= 6; i++) {
      const hue = ((hueBase + 180 + i * 60) % 360 + 360) % 360;
      g2.addColorStop(i / 6, `hsla(${hue.toFixed(0)}, 100%, 55%, 0.4)`);
    }
    ctx.fillStyle = g2;
    ctx.fillRect(cx - r, cy - r, r * 2, r * 2);

    // Specular highlight — 기울기에 따라 반사점 이동
    const specX = cx + tiltX * r * 0.52;
    const specY = cy - tiltY * r * 0.42;
    const sg = ctx.createRadialGradient(specX, specY, 0, specX, specY, r * 0.62);
    sg.addColorStop(0,    'rgba(255, 255, 255, 1.0)');
    sg.addColorStop(0.10, 'rgba(255, 255, 255, 0.65)');
    sg.addColorStop(0.35, 'rgba(255, 255, 255, 0.15)');
    sg.addColorStop(1,    'rgba(255, 255, 255, 0)');
    ctx.globalCompositeOperation = 'screen';
    ctx.fillStyle = sg;
    ctx.fillRect(cx - r, cy - r, r * 2, r * 2);

    // 테두리 어둡게 (구 느낌)
    const vg = ctx.createRadialGradient(cx, cy, r * 0.5, cx, cy, r);
    vg.addColorStop(0, 'rgba(0, 0, 0, 0)');
    vg.addColorStop(1, 'rgba(0, 0, 0, 0.62)');
    ctx.globalCompositeOperation = 'source-over';
    ctx.fillStyle = vg;
    ctx.fillRect(cx - r, cy - r, r * 2, r * 2);

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
