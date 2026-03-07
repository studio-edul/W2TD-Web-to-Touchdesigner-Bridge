# W2TD — Integrated Web-to-TouchDesigner Bridge

> v1.0.0

모바일 브라우저의 센서 데이터, 오디오, 카메라를 WebSocket + WebRTC로 TouchDesigner에 실시간 전송하는 시스템.

```
[모바일 브라우저] ──WebSocket (WSS)──> [Cloudflare 터널] ──> [TouchDesigner Web Server DAT]
  GitHub Pages (HTTPS)                                         포트 9980 (TLS OFF)

[모바일 카메라/마이크] ──WebRTC (P2P)──> [TouchDesigner WebRTC DAT / Web Render TOP]
```

모바일에서 인증서 설정이나 별도 서버 없이 바로 연결됩니다.

---

## 빠른 시작

### 1. TouchDesigner 설정

#### 필수 DAT 노드

| 노드 | 타입 | 이름 | 역할 |
|------|------|------|------|
| Web Server DAT | DAT → Web Server | `web_server_dat` | WebSocket 연결 수신 |
| Callbacks Script | DAT → Text | `callbacks` | `callbacks.py` 내용 |
| Execute DAT | DAT → Execute | `w2td_init` | `w2td_init.py` — TD 시작 시 자동 실행 |
| Table DAT | DAT → Table | `sensor_table` | `init_tables()` 가 자동 생성 |
| Table DAT | DAT → Table | `touch_table` | `init_tables()` 가 자동 생성 |
| Table DAT | DAT → Table | `w2td_config` | 런타임 설정 |

#### 선택 노드 (WebRTC 오디오/카메라)

| 노드 | 타입 | 이름 | 역할 |
|------|------|------|------|
| WebRTC DAT | DAT → WebRTC | `webrtc_dat` | 마이크 WebRTC 연결 처리 |
| Text DAT | DAT → Text | `webrtc_callbacks` | `webrtc_callbacks.py` 내용 |
| Audio Stream In CHOP | CHOP | `webrtc_audio_1` | 마이크 오디오 스트림 수신 |
| Table DAT | DAT → Table | `webrtc_table` | WebRTC 슬롯/연결 상태 추적 |
| Web Render TOP | TOP | `web_render_top` | `cam_receiver.html` 렌더 (카메라 수신) |

**Web Server DAT 파라미터:**
- Active: `On`
- Port: `9980`
- TLS: `Off`

#### w2td_config (Table DAT)

`w2td_config` 이름의 Table DAT를 만들면 코드 수정 없이 설정 변경 가능:

| key | value | 설명 |
|-----|-------|------|
| `max_clients` | `20` | 최대 동시 접속 기기 수 |
| `sample_rate` | `30` | 기본 센서 전송 Hz |
| `dev_mode` | `1` | `1` = 전체 UI, `0` = 미니멀 자동 모드 |
| `haptic_enabled` | `1` | 햅틱 피드백 활성화 |
| `Turnserver` | _(선택)_ | 커스텀 TURN 서버 URL (예: `turn:global.relay.metered.ca:80`) |
| `Turnusername` | _(선택)_ | TURN 사용자명 |
| `Turnpassword` | _(선택)_ | TURN 비밀번호 |

#### w2td_init.py (Execute DAT)

`touchdesigner/w2td_init.py` 내용을 `w2td_init` Execute DAT에 붙여넣습니다.
- TD 시작 시 `onStart()` 자동 실행
- `init_tables()` 호출 → 모든 필수 테이블 초기화
- Cloudflare 터널 시작 + QR 코드 생성

필요한 Python 패키지 (최초 1회 설치):
```
pip install qrcode pillow pycloudflared
```

#### callbacks.py (Web Server DAT Callbacks)

`touchdesigner/callbacks.py` 내용을 Web Server DAT의 Callbacks Script DAT에 붙여넣습니다.

### 2. 모바일 연결

1. TD 실행 → `w2td_init.py`가 Cloudflare 터널 시작 + QR 코드 생성
2. QR 코드 스캔 → `?td=` 파라미터가 채워진 GitHub Pages로 이동
3. 기기 이름 입력 (선택) → **Connect** 탭
4. 센서 자동 수집 시작; **카메라** 또는 **마이크** 버튼으로 WebRTC 스트림 활성화

### 3. TD에서 데이터 읽기

**sensor_table DAT** — 연결된 기기마다 한 행 (슬롯 1~20):

| 컬럼 | 설명 | 범위 |
|------|------|------|
| `slot` | 기기 슬롯 번호 | 1 ~ 20 |
| `connected` | 연결 상태 | 0 또는 1 |
| `name` | 기기 이름 (사용자 지정 또는 자동 감지) | string |
| `ax` `ay` `az` | 가속도 (중력 포함) | m/s² (약 ±15) |
| `ga` `gb` `gg` | 자이로 회전속도 | deg/s |
| `oa` | 오리엔테이션 alpha (나침반/Yaw) | 0 ~ 360° |
| `ob` | 오리엔테이션 beta (앞뒤 기울기/Pitch) | -180 ~ 180° |
| `og` | 오리엔테이션 gamma (좌우 기울기/Roll) | -90 ~ 90° |
| `lat` `lon` | GPS 좌표 | 도(degree) |
| `touch_count` | 현재 터치 개수 | 정수 |
| `trig` | 트리거 버튼 상태 (누르는 동안 1, 뗄 때 0) | 0 또는 1 |
| `css_width` `css_height` | 브라우저 뷰포트 크기 | px |
| `physical_width` `physical_height` | 물리적 화면 크기 | px |
| `screen_width` `screen_height` | 화면 해상도 | px |
| `device_pixel_ratio` | 기기 픽셀 비율 (DPR) | float |

**touch_table DAT** — 활성 터치 포인트마다 한 행:

| 컬럼 | 설명 |
|------|------|
| `slot` | 기기 슬롯 |
| `touch_id` | 터치 인덱스 (0부터) |
| `x` `y` | 터치 위치 (정규화 0~1) |
| `state` | 1 = 터치 중 |

**webrtc_table DAT** — WebRTC 연결 상태:

| 컬럼 | 설명 |
|------|------|
| `slot` | 기기 슬롯 |
| `name` | 기기 이름 |
| `conn_id` | WebRTC DAT 연결 UUID |
| `state` | `connecting` / `connected` / `closed` |

**CHOP으로 읽는 방법:**
- `sensor_table` → **DAT to CHOP** 연결
- `First Row is Names: On`, `Select Rows: By Index` → 행 `1` (슬롯 1번 기기)
- 범위 조정이 필요하면 **Math CHOP** 사용

---

## 동작 구조

- TD Web Server DAT가 포트 `9980`에서 대기 (TLS 없음)
- `w2td_init.py`가 Cloudflare 터널 시작 → 공개 주소 `wss://xxxx.trycloudflare.com`
- QR 코드는 `https://studio-edul.github.io/Integrated-Web-to-TouchDesigner-Bridge/?td=xxxx.trycloudflare.com` 인코딩
- 모바일이 GitHub Pages에 직접 접속 → Cloudflare 터널 경유 WebSocket 연결
- 마이크: WebRTC offer/answer → `webrtc_dat` → Audio Stream In CHOP
- 카메라: WebRTC 릴레이 → `web_render_top` (cam_receiver.html)

### callbacks.py 리로드 후 상태 유지

클라이언트 슬롯 정보는 `op('/').store/fetch`로 저장되어, TD 내에서 스크립트가 리로드되어도 연결이 끊기지 않습니다.

---

## WebSocket 메시지 레퍼런스

### 모바일 → TD

```json
{ "type": "sensor", "ax": -0.12, "ay": 0.34, "az": 9.76, "ga": 12.5, "gb": -3.2, "gg": 0.8,
  "oa": 183.4, "ob": -12.0, "og": 5.3, "lat": 37.5665, "lon": 126.9780 }

{ "type": "touch", "count": 2, "t0x": 0.35, "t0y": 0.72, "t0s": 1, "t1x": 0.68, "t1y": 0.45, "t1s": 1 }

{ "type": "trigger", "value": 1 }   // 버튼 누르는 중(1) / 뗌(0)

{ "type": "ping" }                   // 하트비트 (5초마다)
```

### TD → 모바일

```json
{ "type": "ack", "slot": 1, "td_version": "1.0.0" }

{ "type": "config", "sample_rate": 30, "dev_mode": 1, ... }

{ "type": "haptic", "pattern": [200, 100, 200] }   // 진동 패턴
{ "type": "haptic", "state": 1 }                   // 지속 진동 on/off

{ "type": "data_ack" }    // 데이터 수신 확인
{ "type": "pong" }        // 하트비트 응답
```

---

## TD 햅틱 API

```python
# 특정 슬롯에 진동 패턴 전송
op('web_server_dat').module.send_haptic_to_client(op('web_server_dat'), slot=1, pattern=[200, 100, 200])

# 전체 기기에 진동 전송
op('web_server_dat').module.send_haptic_to_all(op('web_server_dat'), pattern=[200])

# CHOP 기반 진동 제어 (Execute DAT 또는 Timer CHOP에서 주기적으로 호출)
# 'w2td_haptic' CHOP, 채널: slot1, slot2, ... (값 0 또는 1)
op('web_server_dat').module.broadcast_haptic_from_chop(op('web_server_dat'))
```

---

## 주요 기능

- 모션 센서 (가속도계 + 자이로) — 원본 m/s², deg/s 값
- 오리엔테이션 (Yaw/Pitch/Roll) — 원본 도(degree) 값
- 멀티터치 트래킹 (위치 0~1 정규화)
- GPS (위도/경도)
- **트리거 버튼** — hold 기반 (누르는 동안 1, 뗄 때 0)
- **햅틱 피드백** — 패턴 또는 지속 진동, TD CHOP으로 제어
- **마이크** — WebRTC → Audio Stream In CHOP
- **카메라** — WebRTC → Web Render TOP (후면/전면, 기기당 상호 배타)
- **WebSocket 하트비트** — 연결 유지 + 자동 재연결
- **Data Ack** — TD 수신 확인 시각 피드백
- **기기 이름** — 사용자 지정 또는 User-Agent 자동 감지
- **화면 정보** — CSS/물리/해상도 + DPR
- **설정 자동 배포** — w2td_config 변경 시 전체 클라이언트에 즉시 전송
- 최대 20대 동시 연결
- 실시간 Canvas 시각화
- 샘플레이트 조절 (5~60 Hz)
- Wake Lock (화면 꺼짐 방지)
- 자동 재연결 (지수 백오프)

---

## 프로젝트 구조

```
docs/                    ← GitHub Pages (웹 앱)
  index.html
  js/
    app.js               ← 앱 메인 컨트롤러
    sensors.js           ← 센서 감지, 권한
    websocket.js         ← WebSocket 클라이언트, 하트비트, 재연결
    webrtc.js            ← WebRTC (마이크 + 카메라)
    touch.js             ← 터치 이벤트 처리
    visualization.js     ← Canvas 스파크라인 렌더러

touchdesigner/
  callbacks.py           ← Web Server DAT 콜백 (모든 WebSocket 로직)
  w2td_init.py           ← Execute DAT (Cloudflare 터널, QR, 테이블 초기화)
  webrtc_callbacks.py    ← WebRTC DAT 콜백
  config_watch.py        ← w2td_config 변경 감지 자동 브로드캐스트
  haptic_chop_exec.py    ← CHOP 기반 햅틱 Execute DAT 헬퍼
  cam_receiver.html      ← 로컬 서빙; Web Render TOP에서 카메라 수신
```

> **워크플로우:** `docs/` 파일만 GitHub에 push합니다. Python 파일은 TD에서 직접 적용 (파일 수정 시 DAT 자동 업데이트).

---

## 참고 자료

- [Web Server DAT — TouchDesigner Docs](https://docs.derivative.ca/Web_Server_DAT)
- [WebRTC DAT — TouchDesigner Docs](https://docs.derivative.ca/WebRTC_DAT)
- [Device Orientation API — MDN](https://developer.mozilla.org/en-US/docs/Web/API/DeviceOrientationEvent)
- [Device Motion API — MDN](https://developer.mozilla.org/en-US/docs/Web/API/DeviceMotionEvent)
