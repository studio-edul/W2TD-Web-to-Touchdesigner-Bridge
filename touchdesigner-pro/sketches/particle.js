/**
 * Particle Sketch — W2TD canvas_runner compatible
 *
 * 사용법: TD Text DAT에 이 파일 내용을 넣고 canvas_code WebSocket 메시지로 전송.
 *
 * CanvasRunner API:
 *   canvas       — #render-canvas 엘리먼트 (크기는 CanvasRunner가 관리)
 *   requestFrame — requestAnimationFrame 래퍼 (stop 시 자동 취소)
 *   getSensors() — { ax, ay, az, oa, ob, og, ... } 반환
 *
 * 중력 제거 방식:
 *   저역통과필터 대신 오리엔테이션(ob=beta, og=gamma)으로 중력벡터를 계산해
 *   가속도센서 값에서 뺀다. 정적 기울기 상태에서도 정확하게 선형가속도만 추출.
 *
 * 필요 센서: W2TD 앱에서 Motion + Orientation 모두 활성화 필요.
 *   oa/ob/og = 0이면 수평(평면) 기준 중력 제거로 폴백됨.
 */

const ctx = canvas.getContext('2d');
const dpr = window.devicePixelRatio || 1;

const W = () => canvas.width / dpr;
const H = () => canvas.height / dpr;

// ── Tunable Parameters ───────────────────────────────────────────────────────
// TD에서 실시간 제어 대상 변수들 (추후 canvas_params 메시지로 연결 예정)
let PARTICLE_COUNT = 2000;
let EMIT_RATE = 100;
let BASE_SPEED = 1;    // 파티클 기본 초기 속도
let LIFE_MAX = 220;
let FORCE_SCALE = 2;    // x/y 가속도 → 파티클 힘 민감도
let FORCE_MAX = 3.0;    // 선형가속도 클램핑 최대값 (단위: G, 1.0 = 9.8 m/s²)
let SMOOTH_ALPHA = 0.15;  // 저역통과 필터 계수 (0~1, 낮을수록 더 부드럽고 지연 큼)
let TURB_SCALE = 0.05;    // 노이즈 난류 강도
let TURB_FREQ = 0.008;   // 노이즈 난류 주파수
let Z_SCALE = 1.5;     // z축 선형가속도 → 초기속도 민감도
let Z_SPEED_MIN = 0.2;     // z축 multiplier 최솟값 (정지 시 하한)
let Z_SPEED_MAX = 3.0;     // z축 multiplier 최댓값

// 파티클 타입별 크기 범위 (타입0=소, 타입1=중, 타입2=대)
let SIZE_0_MIN = 0.5; let SIZE_0_MAX = 1.0;
let SIZE_1_MIN = 1.0; let SIZE_1_MAX = 2.0;
let SIZE_2_MIN = 2.0; let SIZE_2_MAX = 3.0;

// ── Constants (변경 불필요) ───────────────────────────────────────────────────
const G = 9.8;
const DEG = Math.PI / 180;

// 크기 변수를 참조하는 getter로 정의 — 변수 수정 즉시 반영됨
const TYPES = [
  { get sizeMin() { return SIZE_0_MIN; }, get sizeMax() { return SIZE_0_MAX; }, alphaMax: 1.0 },
  { get sizeMin() { return SIZE_1_MIN; }, get sizeMax() { return SIZE_1_MAX; }, alphaMax: 0.55 },
  { get sizeMin() { return SIZE_2_MIN; }, get sizeMax() { return SIZE_2_MAX; }, alphaMax: 0.18 },
];

// ── State ────────────────────────────────────────────────────────────────────
let force = { x: 0, y: 0, speedMult: 1.0 };
let smoothX = 0, smoothY = 0; // 저역통과 필터 상태
let tick = 0;
let orbPulse = 0;
let sensorsReady = false; // 첫 센서 데이터 수신 전 emit 차단

// ── 노이즈 ───────────────────────────────────────────────────────────────────
function hash(n) { const x = Math.sin(n) * 43758.5453; return x - Math.floor(x); }
function noise2(x, y) {
  const ix = Math.floor(x), iy = Math.floor(y);
  const fx = x - ix, fy = y - iy;
  const u = fx * fx * (3 - 2 * fx), v = fy * fy * (3 - 2 * fy);
  const a = hash(ix + iy * 57), b = hash(ix + 1 + iy * 57);
  const c = hash(ix + (iy + 1) * 57), d = hash(ix + 1 + (iy + 1) * 57);
  return (a + u * (b - a) + v * (c - a) + u * v * (a - b - c + d)) * 2 - 1;
}

// ── 오리엔테이션 기반 중력 벡터 계산 ────────────────────────────────────────
// beta(ob): 앞뒤 기울기 (-180~180°),  gamma(og): 좌우 기울기 (-90~90°)
//
// W3C 스펙 회전 순서: R = Rz(α)·Rx(β)·Ry(γ)  (device→world)
// 역변환으로 world 중력 [0,0,-g] 를 device 좌표로:
//   g_device = Ry(-γ)·Rx(-β)·[0, 0, -g]
//
// 검증 (평면 face-up 기준, az≈-9.8, ay≈-9.8 세로, ax≈+9.8 우측 기울임):
//   평면(b=0, g=0)   → gx=0,    gy=0,    gz=-9.8  linZ=0 ✓
//   세로(b=90, g=0)  → gx=0,    gy=-9.8, gz=0     linY=0 ✓
//   우측(b=0, g=90)  → gx=+9.8, gy=0,    gz=0     linX=0 ✓
function gravityFromOrientation(beta_deg, gamma_deg) {
  const b = beta_deg * DEG;
  const g = gamma_deg * DEG;
  return {
    x: G * Math.sin(g) * Math.cos(b),  // +G (이전 -G 오류), cos(b) 항 추가
    y: -G * Math.sin(b),                 // cos(g) 항 제거
    z: -G * Math.cos(b) * Math.cos(g),
  };
}

// ── Particle ─────────────────────────────────────────────────────────────────
class Particle {
  constructor() { this.active = false; }

  reset(cx, cy, fx, fy, speedMult) {
    const r = Math.random();
    this.type = r < 0.3 ? 0 : r < 0.7 ? 1 : 2;
    const t = TYPES[this.type];

    const angle = Math.random() * Math.PI * 2;
    const speed = BASE_SPEED * speedMult * (0.3 + Math.random() * 0.7) * (this.type === 2 ? 0.6 : 1);

    this.x = cx + (Math.random() - 0.5) * 4;
    this.y = cy + (Math.random() - 0.5) * 4;
    this.vx = Math.cos(angle) * speed;
    this.vy = Math.sin(angle) * speed;

    // 생성 시점 force 고정 저장
    this.ax = fx * FORCE_SCALE;
    this.ay = fy * FORCE_SCALE;

    const lifeScale = this.type === 2 ? 1.3 : 1.0;
    this.life = LIFE_MAX * lifeScale * (0.5 + Math.random() * 0.5);
    this.maxLife = this.life;
    this.size = t.sizeMin + Math.random() * (t.sizeMax - t.sizeMin);
    this.alphaMax = t.alphaMax;
    this.noiseOff = Math.random() * 100;

    this.hue = Math.random() < 0.15 ? (Math.random() < 0.5 ? 200 : 40) : 0;
    this.sat = this.hue === 0 ? 0 : 60 + Math.random() * 40;
    this.active = true;
  }

  update() {
    if (!this.active) return;
    this.vx += this.ax;
    this.vy += this.ay;
    const nx = noise2(this.x * TURB_FREQ + this.noiseOff, tick * 0.25);
    const ny = noise2(this.y * TURB_FREQ + this.noiseOff + 50, tick * 0.25);
    this.vx += nx * TURB_SCALE;
    this.vy += ny * TURB_SCALE;
    const drag = this.type === 2 ? 0.992 : 0.988;
    this.vx *= drag;
    this.vy *= drag;
    this.x += this.vx;
    this.y += this.vy;
    if (--this.life <= 0) this.active = false;
  }

  draw() {
    if (!this.active) return;
    const t = this.life / this.maxLife;
    const alpha = this.alphaMax * Math.pow(t, 0.4) * Math.min(1, (this.maxLife - this.life) / 8);
    if (alpha < 0.005) return;
    const radius = this.size * (0.3 + t * 0.7);
    ctx.beginPath();
    ctx.arc(this.x, this.y, radius, 0, Math.PI * 2);
    ctx.fillStyle = this.hue === 0
      ? `rgba(255,255,255,${alpha})`
      : `hsla(${this.hue},${this.sat}%,95%,${alpha})`;
    ctx.fill();
  }
}

const pool = Array.from({ length: PARTICLE_COUNT }, () => new Particle());

function emit(cx, cy) {
  const fx = force.x, fy = force.y, sm = force.speedMult;
  let n = 0;
  for (let i = 0; i < pool.length && n < EMIT_RATE; i++) {
    if (!pool[i].active) { pool[i].reset(cx, cy, fx, fy, sm); n++; }
  }
}

function drawOrb(cx, cy) {
  orbPulse += 0.04;
  const pulse = 1 + Math.sin(orbPulse) * 0.06;
  ctx.beginPath();
  ctx.arc(cx, cy, 4 * pulse, 0, Math.PI * 2);
  ctx.fillStyle = '#ffffff';
  ctx.fill();
}

// ── 디버그 오버레이 ───────────────────────────────────────────────────────────
function drawDebug(lx, ly, lz, sm) {
  const w = W(), h = H();
  const pad = 12;
  const lh = 18;
  const fs = 13;
  const lines = [
    `linX: ${lx.toFixed(3)} m/s²`,
    `linY: ${ly.toFixed(3)} m/s²`,
    `linZ: ${lz.toFixed(3)} m/s²`,
    `speedMult: ${sm.toFixed(2)}`,
  ];
  ctx.save();
  ctx.font = `${fs}px monospace`;
  ctx.textBaseline = 'bottom';
  const boxH = lines.length * lh + pad;
  ctx.fillStyle = 'rgba(0,0,0,0.55)';
  ctx.fillRect(0, h - boxH, w, boxH);
  lines.forEach((txt, i) => {
    const isZ = i === 2;
    const isSm = i === 3;
    ctx.fillStyle = isSm ? '#aef' : isZ ? '#fda' : '#fff';
    ctx.fillText(txt, pad, h - (lines.length - 1 - i) * lh - pad / 2);
  });
  ctx.restore();
}

// ── Loop ─────────────────────────────────────────────────────────────────────
function loop() {
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

  tick++;
  const w = W(), h = H();
  const cx = w / 2, cy = h / 2;

  // 오리엔테이션으로 중력 벡터 계산 → 가속도에서 차감 → 선형가속도만 추출
  const s = getSensors();

  // az가 0이 아니면 실제 센서 데이터 수신된 것으로 판단 (평면 정지 시 az≈-9.8)
  if (!sensorsReady) {
    if (s.az) {
      sensorsReady = true;
      // 필터 상태를 현재 값으로 초기화 — warmup 아티팩트 방지
      const gInit = gravityFromOrientation(s.ob, s.og);
      smoothX = (s.ax || 0) - gInit.x;
      smoothY = (s.ay || 0) - gInit.y;
    } else { requestFrame(loop); return; }
  }

  const grav = gravityFromOrientation(s.ob, s.og);
  const linX = (s.ax || 0) - grav.x;
  const linY = (s.ay || 0) - grav.y;
  const linZ = (s.az || 0) - grav.z;
  const clamp = (v, lo, hi) => v < lo ? lo : v > hi ? hi : v;

  // Option B: 저역통과 필터 — 걷기 진동 제거, 이동 방향만 추출 (꼬리 효과)
  smoothX = smoothX * (1 - SMOOTH_ALPHA) + linX * SMOOTH_ALPHA;
  smoothY = smoothY * (1 - SMOOTH_ALPHA) + linY * SMOOTH_ALPHA;
  force.x = clamp(smoothX / G, -FORCE_MAX, FORCE_MAX);
  force.y = clamp(-smoothY / G, -FORCE_MAX, FORCE_MAX); // Y축 반전: 캔버스 Y(아래+) vs 센서 Y 방향 보정
  // Option A: 필터 없이 즉각 반응 — 되돌리려면 위 4줄 주석하고 아래 2줄 활성화:
  // force.x = clamp(linX / G, -FORCE_MAX, FORCE_MAX);
  // force.y = clamp(-linY / G, -FORCE_MAX, FORCE_MAX);

  // z축 선형가속도 → 파티클 초기속도 multiplier
  // 앞뒤로 흔들수록(az 큰 변화) 파티클이 더 빠르게 튀어나옴
  const zNorm = linZ / G;
  const rawMult = 1 + zNorm * Z_SCALE;
  force.speedMult = Math.max(Z_SPEED_MIN, Math.min(Z_SPEED_MAX, rawMult));

  ctx.clearRect(0, 0, w, h);
  emit(cx, cy);
  for (const p of pool) { p.update(); p.draw(); }
  drawOrb(cx, cy);

  // ── 디버그 오버레이 (선형가속도 값 표시) — 파티클 위에 렌더
  drawDebug(linX, linY, linZ, force.speedMult);

  requestFrame(loop);
}

requestFrame(loop);
