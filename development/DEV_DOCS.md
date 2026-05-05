# W2TD (Web-to-TouchDesigner Bridge) 개발 문서

> 최종 업데이트: 2026-05-05 (Page Visibility API 추가: 모바일 백그라운드 시 센서값 0으로 초기화 / line_chop.py 센서 활성 판별 강화: az 단일 체크 → az·ga·gb·gg 다중 축 체크)
> 목적: 추후 세션에서 파일 위치·구현 방식을 빠르게 파악하기 위한 참고 문서

---

## 1. 프로젝트 개요

모바일 브라우저의 센서 데이터(가속도계·자이로·GPS·터치)와 마이크를 WebSocket으로 TouchDesigner에 실시간 전송하는 브리지.

```
Mobile Browser (GitHub Pages HTTPS)
  ├─ WebSocket (wss://)
  │    └─ cloudflared 터널 (https://xxxx.trycloudflare.com)
  │         └─ TD Web Server DAT (port 9980, TLS OFF)
  │              └─ callbacks.py → sensor_table / touch_table
  │
  └─ WebRTC (P2P)
       ├─ 마이크 업링크: 모바일 → micPc → TD WebRTC DAT → Audio Stream In CHOP
       ├─ 오디오 다운링크: TD Audio Stream Out CHOP → micPc → 모바일 <audio> 재생
       ├─ 비디오 다운링크: TD Video Stream Out TOP → micPc → 모바일 <video> 재생
       └─ 카메라: 모바일 → camPc → Web Render TOP (cam_receiver.html)
```

---

## 2. 빠른 시작 가이드

### 2-1. 초기 설정 (기기당 1회)

**1단계: `w2td_init` Execute DAT 생성 + 스크립트 연결**

`w2td_init.py`의 `onCreate()`가 자동으로 아래 패키지를 설치합니다 (`install_packages()` 호출):

- `certifi` (SSL 인증서, macOS에서 특히 중요)
- `qrcode[pil]` (QR 코드 생성)
- `pycloudflared` (Cloudflare 터널)
- `scipy` (선택 — position estimator 등에서 사용)

수동 재설치가 필요하면 Textport에서:
```python
op('w2td_init').module.install_packages()
```

**2단계: TouchDesigner 재시작**

설치 후 TD를 재시작하면 SSL 인증서가 깨끗하게 로드됩니다.

### 2-2. TouchDesigner 프로젝트 설정

모든 W2TD 노드는 베이스 COMP 안에 배치한다. 프리는 `W2TD`, 프로는 `W2TD_Pro`.

**베이스 COMP 내부 최상위 노드:**

| 노드 이름 | 타입 | 용도 |
|-----------|------|------|
| `web_server_dat` | Web Server DAT | WebSocket + HTTP 연결 수신 (port 9980, TLS Off) |
| `callbacks` | Text DAT | Web Server DAT의 Callbacks Script에 연결. `callbacks.py` 내용 |
| `w2td_init` | Execute DAT | `w2td_init.py`. `onCreate` = 패키지 설치, `onStart` = 터널+QR |
| `sensor_table` | Table DAT | `_init_tables()`에서 헤더 자동 셋업, row는 동적 |
| `touch_table` | Table DAT | `_init_tables()`에서 헤더 자동 셋업 |
| `w2td_config` | Table DAT | 선택 — 설정값 오버라이드 (key / value 형식) |
| `config_watch` | DAT Execute | `w2td_config`를 감시 → 변경 시 debounce 후 자동 broadcast |
| `cam_receiver_html` | Text DAT | `cam_receiver.html` 내용. Web Server DAT이 로컬 HTTP로 서빙 |
| `qr_movie_top` | Movie File In TOP | 선택 — 생성된 QR 이미지 표시 |
| 베이스 COMP 자체 | COMP | 선택 — custom `url` 파라미터로 QR URL 표시 |

**`webrtc_audio_container` 서브 컴포넌트 (WebRTC 오디오 RX + 오디오 TX):**

| 노드 이름 | 타입 | 용도 |
|-----------|------|------|
| `webrtc_dat` | WebRTC DAT | 모든 WebRTC 연결 (마이크 + 오디오/비디오 다운링크). Callbacks DAT=`webrtc_callbacks` |
| `webrtc_callbacks` | Text DAT | `webrtc_callbacks.py` |
| `webrtc_table` | Table DAT | 슬롯/conn_id/state 매핑 |
| `webrtc_table_sync` | DAT Execute | `webrtc_table` 변경 감지 → 슬롯별 CHOP/TOP 자동 생성/삭제 |
| `webrtc_audio_merge` | Merge CHOP | 모든 `webrtc_audio_{N}` 머지 |
| `rename1` | Rename CHOP | 머지된 채널을 기기 이름으로 변경 |
| `w2td_audio_bus` | Constant CHOP | (선택, Pro) 오디오 다운링크 입력. 채널: `slot1`, `slot2`, ... |

슬롯별 자동 생성 (webrtc_table_sync가 관리):
- `webrtc_audio_{N}` — Audio Stream In CHOP (마이크 업링크)
- `select_slot{N}` + `webrtc_audio_out_{N}` — 오디오 다운링크 (Pro)

**`webrtc_video_container` 서브 컴포넌트 (카메라 업링크 + 비디오 다운링크 TX):**

| 노드 이름 | 타입 | 용도 |
|-----------|------|------|
| `cam_render_sync` | DAT Execute | `sensor_table` 변경 감지 → 슬롯별 카메라 수신 파이프라인 관리 |
| `webrtc_video_sync` | DAT Execute | `webrtc_table` 변경 감지 → 슬롯별 비디오 TX 파이프라인 관리 (Pro) |
| `layout1` | Layout TOP | 슬롯이 하나라도 연결되면 자동 생성 — 모든 슬롯 컴포지트 |

카메라 업링크 (cam_render_sync 관리): `web_render_top_{N}` → `transform_top_{N}` (rotate) → `crop_top_{N}` → `camera_slot{N}` (null TOP) → `layout1`

비디오 TX 다운링크 (webrtc_video_sync 관리, Pro):
사용자가 베이스 COMP 밖(`project1`)에 `video_slot{N}` TOP을 배치하면 자동으로 파이프라인이 생성된다:
`select_video_slot{N}` (`../../video_slot{N}` 참조) → `flip_top_{N}` (flipX) → `video_stream_out_{N}`

노드 Y좌표 배치: `BLOCK_HEIGHT=300`, cam 노드 Y=`-idx*300`, webrtc TX 노드 Y=`-idx*300-150-100`. 두 파일의 BLOCK_HEIGHT 반드시 동일 유지.

**Web Server DAT 설정:**
- Active: `On`
- Port: `9980`
- TLS: `Off` (cloudflared 필수)

**Execute DAT (`w2td_init`) 설정:**
- DAT = `w2td_init.py` 내용
- Run on: `OnCreate` (패키지 설치) + `OnStart` (터널/QR)

### 2-3. 사용 방법

1. TouchDesigner 실행 → `w2td_init.py`가 자동으로:
   - cloudflared 터널 생성
   - QR 코드 생성
   - QR URL 표시

2. 모바일 기기로 QR 코드 스캔 → GitHub Pages가 TD 주소와 함께 열림

3. **Enable Sensors** 탭 → 센서가 자동으로 활성화됨

4. 데이터가 즉시 TD로 스트리밍됨 → `sensor_table`과 `touch_table` 확인

### 2-4. 문제 해결

**Cloudflare 터널 실패 → 로컬 IP로 폴백:**
- SSL 인증서 설치 확인 (섹션 17 참조)
- `certifi` 재설치: `op('w2td_init').module.install_packages()`
- 설치 후 TouchDesigner 재시작

**QR 코드가 cloudflare URL 대신 로컬 IP 표시:**
- SSL 인증서 문제 (macOS에서 흔함) — 섹션 17 참조
- Textport 로그에서 `[W2TD] SSL certificates configured` 메시지 확인

---

## 3. 파일 구조 전체 맵

```
Integrated-Web-to-TouchDesigner-Bridge/
├── docs/                          ← GitHub Pages 배포 (HTTPS) — Non-Commercial 버전
│   ├── index.html
│   ├── css/style.css
│   └── js/
│       ├── websocket.js           ← WebSocket 연결 관리
│       ├── sensors.js             ← 센서 감지·권한·데이터 수집
│       ├── touch.js               ← 멀티터치 추적·정규화
│       ├── visualization.js       ← Canvas 스파크라인 그래프 + 터치 시각화
│       ├── webrtc.js              ← WebRTC 피어 연결·마이크·오디오 수신
│       └── app.js                 ← 전체 조율 컨트롤러 (메인 앱)
│
├── docs-pro/                      ← Pro 버전 웹 파일
│   ├── index.html                 ← gsap, THREE, p5 CDN 로드 (canvas sketch용)
│   ├── css/style.css
│   └── js/
│       ├── websocket.js           ← WebSocket (haptic, bg_color, flashlight, canvas_code 콜백 추가)
│       ├── sensors.js
│       ├── touch.js
│       ├── visualization.js
│       ├── webrtc.js              ← WebRTC + handleOffer (TD-initiated 오디오 다운링크)
│       ├── canvas_runner.js       ← CanvasRunner — JS 스케치 실행 (new Function 패턴)
│       ├── audio.js               ← (레거시 — 현재 미사용, WebRTC로 대체)
│       └── app.js                 ← Pro 기능 포함 (Videoout 모드 게이트, 배경색, 플래시라이트, 스케치)
│
├── touchdesigner/
│   └── py/                        ← 프리 버전 (base COMP: W2TD)
│       ├── callbacks.py           ← Web Server DAT 콜백 (sensor/touch/webrtc 시그널링)
│       ├── w2td_init.py           ← onCreate=install_packages / onStart=터널+QR
│       ├── webrtc_callbacks.py    ← WebRTC DAT 콜백 (onOffer/onAnswer/onIce)
│       ├── config_watch.py        ← w2td_config 변경 감지 → broadcast
│       ├── cam_render_sync.py     ← 슬롯별 web_render_top 파이프라인 자동 관리
│       ├── webrtc_table_sync.py   ← Audio Stream In CHOP (마이크 RX) 자동 관리
│       └── w2td_zombie_checker.py ← 주기적으로 좀비 연결 정리
│
├── touchdesigner-pro/
│   └── py/                        ← Pro 버전 (base COMP: W2TD_Pro)
│       ├── callbacks.py           ← 프리 + 오디오/비디오 다운링크, bg_color, haptic, flashlight, canvas_code 핸들러
│       ├── w2td_init.py           ← 프리 + scipy 설치 포함
│       ├── webrtc_callbacks.py    ← onOffer 포함 — TD-initiated offer 전송
│       ├── config_watch.py        ← 프리 + 배경/플래시/비디오 TX 키 포함, 해상도/회전 자동 반영
│       ├── cam_render_sync.py     ← web_render_top → transform_top → crop_top → layout1 자동 연결
│       ├── webrtc_table_sync.py   ← Audio RX/TX 자동 관리 (webrtc_audio_container 내)
│       ├── webrtc_video_sync.py  ← Video TX 자동 관리 (webrtc_video_container 내, 분리됨)
│       ├── canvas_code_dat_exec.py ← DAT Execute — js_code_in 변경 감지 → send_canvas_code_to_all 호출
│       ├── haptic_chop_exec.py    ← w2td_haptic CHOP → haptic 메시지 (slot{N}/all 채널)
│       ├── background_chop_exec.py ← w2td_background 또는 w2td_color (전체) / w2td_bg_color_bus (슬롯별 slot{N}_r/g/b) → bg_color
│       ├── flashlight_chop_exec.py ← w2td_flashlight CHOP → flashlight 메시지
│       ├── update_execs.py        ← 콜백 DAT들 재연결 유틸리티
│       └── w2td_zombie_checker.py ← 주기적으로 좀비 연결 정리
│
├── touchdesigner-examples/
│   └── canvas_sketches/
│       ├── sensor_test.js         ← 스케치 예제: 관성 공 + CodePen 스타일 holofoil(5레이어) + 심장박동 (센서 확인용)
│       └── sensor_diagnostic.js   ← 진단용 스케치: THREE.js 3D 폰 모델 + 자이로 링 + 2D HUD 스파크라인
│
├── development/
│   ├── DEV_DOCS.md                ← 이 파일
│   ├── WEBRTC_PLAN.md
│   ├── webrtc-slot-audio-streaming-guide.md  ← WebRTC 오디오 다운링크 구현 가이드
│   └── ...
│
├── README.md                      ← 영문 README
└── README_KR.md                   ← 한국어 README
```

### 배포/적용 규칙

| 파일 종류 | 적용 방법 |
|---|---|
| `docs/` 웹 파일 | `git push` → GitHub Pages 자동 배포 |
| `touchdesigner/*.py` | 디스크의 .py 파일을 TD가 직접 읽음 — 저장만 하면 TD에 즉시 반영 |
| `touchdesigner/*.toe` | 바이너리 — 수동 저장. 보통 push 안 함 |

---

## 4. 아키텍처 상세

### 4-1. 연결 흐름

```
모바일 QR 스캔
  → GitHub Pages /?td=xxxx.trycloudflare.com
  → WebSocket 연결 (wss://xxxx.trycloudflare.com)
  → TD onWebSocketOpen → slot 할당 → ack + config 전송
  → 모바일: config 수신 → 센서/마이크 자동활성화
  → 모바일: sensor 메시지 브로드캐스트 → TD sensor_table 업데이트
```

### 4-2. 슬롯 시스템

- 클라이언트마다 슬롯 번호(1~MAX_CLIENTS) 할당
- `op('/').store('w2td_client_slots', dict)` — addr → slot 매핑
- `op('/').store('w2td_free_slots', list)` — 남은 슬롯 목록
- 연결 끊기면 슬롯 반납, `sensor_table` 행 삭제

### 4-3. Config 시스템 (TD → 모바일)

TD의 `w2td_config` Table DAT에서 값을 읽어 연결 시 모바일로 push. 키는 `config_watch.py`가 `Samplerate` / `samplerate` / `sample_rate` 여러 변형을 모두 허용.

| w2td_config 키 | 기본값 | 설명 |
|---|---|---|
| `Samplerate` | 30 | 브로드캐스트 Hz |
| `Wakelock` | 1 | 화면 잠금 방지 |
| `Haptic` | 1 | 진동 피드백 사용 가능 여부 (브라우저) |
| `Motion` | 1 | 가속도+자이로 활성화 |
| `Orientation` | 1 | 방향각 활성화 |
| `Geolocation` | 1 | GPS 활성화 |
| `Touch` | 1 | 터치 활성화 |
| `Devmode` | 1 | 1=풀 UI, 0=터치패드만 |
| `Rearcamera` | 0 | 후면 카메라 WebRTC 활성화 |
| `Frontcamera` | 0 | 전면 카메라 WebRTC 활성화 |
| `Microphone` | 1 | 마이크 WebRTC 자동활성화 |
| `Echocancellation` | 0 | 에코 제거 (0=끔/원본, 1=켜짐) |
| `Noisesuppression` | 0 | 노이즈 억제 (0=끔/원본, 1=켜짐) |
| `Audiogain` | 0 | 자동 게인 (0=끔/원본, 1=켜짐) |
| `Showdots` | 1 | 브라우저 상단 좌측 슬롯 도트 표시 |
| `Backgroundcolor` | 1 | (Pro) bg_color 메시지 수신 활성화 |
| `Flashlight` | 1 | (Pro) flashlight 메시지 수신 활성화 |
| `Hapticfeedback` | 1 | (Pro) 햅틱 메시지 수신 활성화 |
| `Video` | 1 | (Pro) TD→모바일 비디오 다운링크 활성화 |
| `Videoout` | `none` | (Pro) 모바일 디스플레이 모드. `none`=비활성, `color`=배경색 제어, `js`=JS 스케치, `td`=TD 비디오 스트림. `Video` 키도 허용 (대소문자 무관 fallback). `config_watch.py`가 변경 즉시 broadcast — 재연결 불필요. |
| `Jsfile` | (없음) | (Pro) JS 스케치 파일 절대 경로. `Videoout=js` + `Jsfile` 설정 시 config_watch가 파일을 읽어 `canvas_code` 메시지로 전체 전송 |
| `Canvastopbar` | 1 | (Pro) JS 스케치 모드에서 상단 바 표시 (`0`=숨김, `1`=표시) |
| `Turnserver` | (없음) | 다른 네트워크용 TURN 서버 주소 (예: `turn:global.relay.metered.ca:80`) |
| `Turnusername` | (없음) | TURN 사용자명 |
| `Turnpassword` | (없음) | TURN 비밀번호 |
| `ice_transport_policy` | (없음) | `relay` = TURN만 사용 (터널/다른 네트워크 시 강제) |
| `Maxclients` | 20 | 최대 접속 수 |
| `Resolution` | Non-Commercial | 카메라 해상도: `Non-Commercial`(1280×1280 정사각), `FHD`(1920×1920 정사각) |
| `Screenmode` | Portrait | 카메라 방향: `Portrait`(세로 크롭), `Landscape`(가로 크롭, rotate -90°) |
| `Port` | 9980 | Web Server DAT 포트 |
| `Fixedurl` | (없음) | 고정 cloudflared named tunnel 도메인. 설정 시 random tunnel 건너뜀 |

---

## 5. 웹 파일 상세

### 5-1. `docs/index.html`

HTML 뼈대. JavaScript 로드 순서가 의존성 순서와 동일해야 함.

```
websocket.js → sensors.js → touch.js → visualization.js → webrtc.js → app.js
```

**주요 DOM 요소 ID**

| ID | 역할 |
|---|---|
| `connection-modal` | 초기 주소 입력 모달 |
| `main-ui` | 메인 UI 컨테이너 (dev_mode=1) |
| `sensor-list` | JS로 렌더링되는 센서 목록 (`<ul>`) |
| `touch-pad` | 풀스크린 터치패드 오버레이 |
| `touch-canvas` | 터치패드 canvas |
| `viz-canvas` | 센서 시각화 canvas |
| `broadcast-bar` | 하단 브로드캐스트 바 |
| `user-start-overlay` | iOS 권한 요청용 TAP TO START 오버레이 |
| `w2td-loading` | QR 접속 후 config 대기 로딩 화면 |
| `webrtc-preview` | 카메라 미리보기 video (현재 미사용) |
| `td-stream-monitor` | TD 비디오 스트림 모니터 오버레이 (dev_mode=1, Pro) |
| `btn-td-stream` | TD 스트림 모니터 진입 버튼 (비디오 수신 시 자동 표시, dev_mode=1) |
| `btn-exit-td-stream` | TD 스트림 모니터 나가기 버튼 |
| `camera-monitor` | 풀스크린 카메라 미리보기 오버레이 (Pro) |
| `webrtc-td-stream` | TD에서 수신한 video 엘리먼트 (JS로 동적 생성) |

---

### 5-2. `docs/css/style.css`

다크 테마 CSS. CSS 변수(`--bg`, `--primary`, `--success` 등) 사용.

**주요 섹션**

| 위치 | 내용 |
|---|---|
| 상단 | 오버레이 스타일 (`#devmode-overlay`, `#rejected-overlay`) |
| 중간 | 레이아웃 (`#main-ui`, `#top-bar`, `#sensor-panel`, `#broadcast-bar`) |
| 센서 목록 | `.sensor-list li.available`, `.selected`, `.deselected`, `.unavailable` |
| 버튼 | `.btn`, `.btn-primary`, `.btn-small`, `.btn-small:disabled` |
| WebRTC 상태 | `.sensor-list li.available.selected.rtc-connected` (파란 테두리) |
| 터치패드 | `#touch-pad`, `.btn-exit-touch` |

**센서 목록 아이템 CSS 클래스 패턴**

```css
.available.deselected  /* 탭 가능, 비활성 */
.available.selected    /* 활성 (초록 테두리) */
.available.selected.rtc-connected  /* WebRTC 연결됨 (파란 테두리) */
.unavailable           /* 비활성화/사용불가 (희미하게) */
```

---

### 5-3. `docs/js/websocket.js` — `WSClient`

TD WebSocket 연결 관리. IIFE 패턴.

**주요 메서드**

| 메서드 | 설명 |
|---|---|
| `WSClient.connect(url, callbacks)` | 연결 시작. callbacks: `onStatusChange`, `onErrorDetail`, `onConfig`, `onWebRTCSignal` |
| `WSClient.send(obj)` | JSON 직렬화 후 전송. 미연결 시 false 반환 |
| `WSClient.sendSensorData(data)` | 센서 데이터 flat JSON 전송 |
| `WSClient.sendTouchData(data)` | 터치 데이터 전송 |
| `WSClient.isConnected()` | 연결 상태 |
| `WSClient.getPacketsPerSec()` | 현재 전송 속도 |

**메시지 라우팅** (onmessage 내부)

```
msg.type === 'ack'                → onStatusChange('connected')
msg.type === 'config'             → onConfig(msg)
msg.type === 'webrtc_answer'      → onWebRTCSignal(msg)
msg.type === 'webrtc_offer'       → onWebRTCSignal(msg)  ← TD-initiated 오디오 다운링크
msg.type === 'webrtc_ice'         → onWebRTCSignal(msg)
msg.type === 'webrtc_state'       → onWebRTCSignal(msg)
msg.type === 'webrtc_renegotiate' → onWebRTCSignal(msg)
msg.type === 'webrtc_answer_cam'  → onWebRTCSignal(msg)
msg.type === 'webrtc_ice_cam'     → onWebRTCSignal(msg)
msg.type === 'cam_receiver_ready' → onWebRTCSignal(msg)
msg.type === 'haptic'             → onHaptic(msg)
msg.type === 'bg_color'           → onBgColor(msg)  (Pro)
msg.type === 'flashlight'         → onFlashlight(msg)  (Pro)
msg.type === 'rejected'           → onStatusChange('rejected'), 재연결 중단
```

**Page Visibility (백그라운드 감지)**

`connect()` 호출 시 `_setupVisibilityListener()`가 `visibilitychange` 이벤트 리스너를 등록한다 (중복 등록 방지 플래그 `visibilityListenerAdded` 사용).

```
홈버튼 / 앱 전환 → document.hidden = true → visibilitychange 발생
  → WSClient.send({ type: 'visibility', state: 'hidden' })
  → TD callbacks.py: sensor_table 해당 슬롯 ax/ay/az/ga/gb/gg/oa/ob/og/lat/lon/touch_count = 0
                     touch_table 해당 슬롯 행 삭제
다시 복귀 → document.hidden = false → visibilitychange 발생
  → WSClient.send({ type: 'visibility', state: 'visible' })
  → TD callbacks.py: 로그만 출력, 이후 sensor 메시지가 오면 자연스럽게 복원
```

- 브라우저 탭 닫기는 `visibilitychange`가 발생하지 않음 → WebSocket 끊김(`onWebSocketClose`)으로 감지
- 화면 잠금은 iOS: 발생, Android: 기기마다 다름
- WebSocket이 닫혀 있으면 `send()`가 아무것도 하지 않으므로 안전

---

### 5-4. `docs/js/sensors.js` — `SensorModule`

센서 감지·권한 요청·데이터 수집. 시뮬레이션 모드(PC) 내장.

**주요 메서드**

| 메서드 | 설명 |
|---|---|
| `detect()` | 브라우저에서 사용 가능한 센서 반환 (`{motion, orientation, geolocation, touch}`) |
| `needsPermissionRequest()` | iOS 여부 확인 (DeviceMotionEvent.requestPermission 존재 여부) |
| `requestPermissions()` | iOS 권한 팝업 — **반드시 user gesture 직접 핸들러에서 호출** |
| `startListening()` | 센서 수집 시작. PC라면 자동으로 시뮬레이션 모드 |
| `stopListening()` | 수집 중지 + 데이터 초기화 |
| `getData()` | `selected` 플래그에 따라 null 필터링된 현재 데이터 |
| `toggleSensor(key)` | 특정 센서 on/off 토글 |
| `setSensorSelected(key, bool)` | config에서 직접 설정 시 사용 |

**데이터 구조**

```javascript
{
  accel:  { x, y, z }          // m/s², 중력 포함 (accelerationIncludingGravity)
  gyro:   { alpha, beta, gamma } // deg/s (rotationRate)
  orient: { alpha, beta, gamma } // deg (alpha: 0~360, beta: -180~180, gamma: -90~90)
  geo:    { lat, lon }
}
```

---

### 5-5. `docs/js/touch.js` — `TouchModule`

멀티터치 추적. 좌표를 0.0~1.0으로 정규화.

**주요 메서드**

| 메서드 | 설명 |
|---|---|
| `init(element, callback)` | 터치 이벤트 리스너 등록. callback(snapshot) 형태 |
| `destroy()` | 리스너 해제 + 상태 초기화 |
| `getSnapshot()` | `{ touches: [{id, x, y, state}], count }` |

- `state`: 1=down, 0=up
- `id`: `Touch.identifier` (브라우저 내부값, 큰 숫자)
- 시각화 레이블은 배열 인덱스+1 (#1, #2...) 사용 (`visualization.js`에서)

---

### 5-6. `docs/js/visualization.js` — `Visualization`

Canvas 2D 렌더링. 두 가지 기능:
1. 센서 스파크라인 그래프 (`#viz-canvas`)
2. 터치 포인트 시각화 (`#touch-canvas`)

**그래프 구성**

3개 그룹: Accel(X/Y/Z), Gyro(α/β/γ), Orient(α/β/γ)
- 히스토리 버퍼: Float32Array(120) ≒ 2초 @ 60fps
- 각 채널 `norm(v)` 함수로 -1~1 정규화 후 플롯

**터치 시각화 모드**

| `showFull` | 표시 내용 |
|---|---|
| `true` (dev_mode=1) | 격자 + 크로스헤어 + `#1 (x, y)` 레이블 + 원형 |
| `false` (dev_mode=0) | 원형만 |

**주요 메서드**

| 메서드 | 설명 |
|---|---|
| `init(canvas)` | ResizeObserver로 자동 리사이즈 |
| `update(sensorData)` | 히스토리 버퍼 업데이트 + 렌더 |
| `drawTouches(canvas, touches, showFull)` | 터치 포인트 렌더 |

---

### 5-7. `docs/js/webrtc.js` — `WebRTCModule`

WebRTC 피어 연결 관리. 시그널링은 기존 WebSocket 재활용.

**카메라 해상도/화면모드**: config의 `cam_resolution`, `camera_screenmode`로 제어. 모바일은 정사각 캡처 후 TD에서 crop.
- Resolution: `non-commercial`(1280×1280), `fhd`(1920×1920)
- Screenmode: `Portrait`(세로 크롭), `Landscape`(가로 크롭 + TD에서 rotate -90°)

**ICE 서버**: Google STUN × 2 + openrelay.metered.ca TURN (무료)

**`_enhanceOpusSdp(sdp)`** (free + Pro): 마이크 offer SDP에 Opus 파라미터를 주입해 음질 개선. `maxaveragebitrate=64000`(기본 ~32kbps → 64kbps), `useinbandfec=1`(FEC 활성화), `usedtx=0`(묵음 구간 패킷 끊김 방지). `start()` → `createOffer()` 직후 SDP에 적용 후 `setLocalDescription`.

**주요 메서드**

| 메서드 | 설명 |
|---|---|
| `start({camera, mic})` | getUserMedia → RTCPeerConnection → offer 전송. 실패 시 `false` 반환 |
| `stop()` | 스트림 해제 + PC 닫기 |
| `handleAnswer(sdp)` | TD에서 온 answer 처리 |
| `handleOffer(sdp)` | TD-initiated offer 처리 (오디오/비디오 다운링크 재협상) → answer 자동 전송 |
| `handleIce({candidate, sdpMLineIndex, sdpMid})` | TD에서 온 ICE candidate 처리 |
| `renegotiate()` | 기존 PC에서 createOffer 재실행 (브라우저-initiated, 현재 미사용) |
| `onStateChange(fn)` | state 변화 콜백 등록. state: `connecting|connected|failed|closed` |
| `setOnTdVideoTrack(fn)` | TD에서 video track 수신 시 콜백 등록. `fn(videoEl, track)` 형태 |
| `isTdVideoActive()` | TD video track 수신 중 여부 (`#webrtc-td-stream` 확인) |
| `isMicActive()` | 마이크 스트림 활성 여부 |
| `isPCActive()` | RTCPeerConnection 존재 여부 (마이크 OFF여도 PC 활성 가능) |
| `getLastError()` | getUserMedia 실패 시 에러명 (e.g. `NotAllowedError`) |

**시그널링 흐름 (마이크 업링크)**

```
모바일 click Microphone
  → getUserMedia({ audio: true })   ← 권한 팝업
  → RTCPeerConnection 생성
  → createOffer → WSClient.send({ type:'webrtc_offer', sdp })
  → TD: setRemoteDescription + createAnswer
  → TD: webrtc_callbacks.onAnswer → webSocketSendText({ type:'webrtc_answer' })
  → 모바일: handleAnswer → setRemoteDescription
  → ICE 교환 (webrtc_ice 양방향)
  → WebRTC P2P 연결 완료
```

**시그널링 흐름 (TD → 모바일 오디오/비디오 다운링크)**

```
WebRTC 연결 완료 후 webrtc_table 갱신
  → webrtc_table_sync.py sync() 호출
  → Select CHOP + Audio Stream Out CHOP 자동 생성
  → (w2td_video_bus TOP 존재 시) Video Stream Out TOP 자동 생성
  → TD: webrtcDAT.addTrack(conn_id, 'audio_out_{slot}', 'audio')  ← 오디오 있을 때
  → TD: webrtcDAT.addTrack(conn_id, 'video_out_{slot}', 'video')  ← 비디오 있을 때
  → TD: webrtcDAT.createOffer(conn_id)    ← delayFrames=3
  → TD: webrtc_callbacks.onOffer → webSocketSendText({ type:'webrtc_offer', sdp })
  → 모바일: handleOffer → setRemoteDescription + createAnswer
  → 모바일: WSClient.send({ type:'webrtc_reanswer', sdp })
  → TD: callbacks.py webrtc_reanswer 핸들러 → setRemoteDescription
  → TD: _auto_select_tx_track() → Audio Stream Out CHOP WebRTC Track 자동 선택
  → TD: _auto_select_video_track() → Video Stream Out TOP WebRTC Track 자동 선택
  → 모바일 ontrack:
       audio track → <audio> 엘리먼트 생성 → 재생
       video track → <video id="webrtc-td-stream"> 생성 → setOnTdVideoTrack 콜백 호출
         dev_mode=1: "TD Stream" 버튼 표시, td-stream-monitor 오버레이에 비디오 배치
         dev_mode=0: 풀스크린 fixed 배경으로 표시 (z-index:501, touch-pad 뒤 배경)
```

---

### 5-8. `docs/js/app.js` — 메인 컨트롤러

모든 모듈을 조율하는 IIFE.

**주요 상태 변수**

| 변수 | 의미 |
|---|---|
| `broadcasting` | 센서 브로드캐스트 중 여부 |
| `sampleRate` | 브로드캐스트 Hz (config로 변경) |
| `devMode` | true=풀UI / false=터치패드만 |
| `touchPadActive` | 터치패드 표시 중 여부 |
| `cameraRearEnabled` | 후면 카메라 활성 여부 (상호배타) |
| `cameraFrontEnabled` | 전면 카메라 활성 여부 (상호배타) |
| `micEnabled` | config/클릭으로 설정된 마이크 활성 의도 |
| `cameraResolutionFromConfig` | 카메라 해상도 (Non-Commercial/FHD/4K) |
| `cameraScreenmodeFromConfig` | 카메라 화면모드 (Portrait/Landscape) |
| `tdStreamMonitorActive` | TD 스트림 모니터 오버레이 표시 중 여부 |

**주요 함수**

| 함수 | 역할 |
|---|---|
| `init()` | DOM 캐시 → 설정 로드 → 이벤트 바인딩 → URL ?td= 자동연결 |
| `applyConfig(cfg)` | TD config 메시지 처리 (sample_rate, 센서 선택, dev_mode, 마이크 등) |
| `applyDevMode(on)` | dev_mode=0: 메인 UI 숨기고 터치패드 직접 표시 |
| `renderSensorList()` | 센서 목록 재렌더. Motion/Orient/Geo/Touch/Camera/Mic 항목 포함 |
| `handleConnect()` | WebSocket 연결 시작 → 로딩화면 또는 UI 표시 |
| `handleMicToggle()` | 마이크 토글. 클릭 즉시 `micEnabled=true` → UI 업데이트 → WebRTC 시작 |
| `handleRearCameraToggle()` | 후면 카메라 토글. 전면 활성 시 상호배타로 전면 중지 후 후면 활성화 |
| `handleFrontCameraToggle()` | 전면 카메라 토글. 후면 활성 시 상호배타로 후면 중지 후 전면 활성화 |
| `handleEnableSensors()` | 센서 권한 요청 + 수집 시작/중지 |
| `enterTouchPad()` / `exitTouchPad()` | 터치패드 전환 |
| `enterTdStreamMonitor()` / `exitTdStreamMonitor()` | TD 비디오 스트림 모니터 오버레이 전환 (dev_mode=1) |
| `enterCameraMonitor()` / `exitCameraMonitor()` | 카메라 미리보기 오버레이 전환 |
| `startBroadcast()` / `stopBroadcast()` | setInterval로 센서 데이터 주기 전송 |
| `_showTouchPadDirectly()` | dev_mode=0 진입 시 — iOS 첫 탭으로 센서 권한 요청 처리 |
| `_startWebRTC()` | config 자동활성화용. WSClient 연결 확인 후 WebRTC 시작 |
| `_webrtcStartOpts(opts)` | ICE 서버·cameraResolution·cameraScreenmode를 opts에 추가 |
| `_cameraOpts()` | cameraResolutionFromConfig, cameraScreenmodeFromConfig 반환 |

**센서 목록 렌더링 패턴**

`renderSensorList()`는 다음 이벤트 발생 시 항상 호출됨:
- 센서 항목 탭
- WebRTC 상태 변화 (`onStateChange`)
- `handleMicToggle` 시작·종료 시
- `applyConfig` 에서 sensor_microphone 변경 시

---

### 5-9. `docs-pro/js/app.js` — Videoout 모드 게이트

Pro 버전의 app.js는 `Videoout` config 값에 따라 배경색·스케치·TD 비디오를 상호배타적으로 활성화한다.

**`displayMode` 변수** (string | null)

| 값 | 의미 |
|---|---|
| `null` | 미설정 (초기값) — 게이트 없이 모든 메시지 허용 |
| `'none'` | 비활성화 |
| `'color'` | 배경색 모드 — `onBgColor` 허용, 스케치/TD영상 중단 |
| `'js'` | JS 스케치 모드 — `onCanvasCode` 허용, 배경색/TD영상 중단 |
| `'td'` | TD 비디오 모드 — 수신 즉시 td-stream-monitor 자동 오픈 |

`applyConfig(cfg)` 에서 `cfg.videoout` 값을 받아 `displayMode`에 저장하고 `_applyDisplayMode()` 호출.

**`_applyDisplayMode()` 동작 (v3 — dev_mode별 분기):**

**`dev_mode=0`**: 기존 자동 전환 유지.
- `'color'`: 배경색 즉시 적용, mainUI 숨김
- `'js'`: `cachedCanvasCode`가 있으면 즉시 `CanvasRunner.load(code)`, mainUI 숨김
- `'td'`: 비디오 활성 시 td-stream-monitor 자동 오픈, mainUI 숨김
- `'none'`: mainUI 복원, 모든 출력 비활성

**`dev_mode=1`**: 자동 전환 없음. `_updateFullscreenButtonVisibility()` 호출만 하고 리턴. 모드별 전용 버튼이 broadcast-bar에 표시되며, 버튼을 탭해야 fullscreen으로 진입한다.

| 버튼 | 표시 조건 | 진입 함수 |
|------|----------|---------|
| "TD Stream" | `displayMode === 'td'` | `enterTdStreamMonitor('td')` |
| "JS Sketch" | `displayMode === 'js'` | `enterTdStreamMonitor('js')` |
| "Color View" | `displayMode === 'color'` | `enterTdStreamMonitor('color')` |

**`_devFullscreenMode`** (string | null): dev_mode=1에서 현재 fullscreen 상태 추적 (`'td'` / `'js'` / `'color'` / null).

**`enterTdStreamMonitor(mode)` 동작 (dev_mode=1):**
- `'td'`: td-stream-monitor 오버레이 표시, mainUI 숨김
- `'js'`: `CanvasRunner.load(cachedCanvasCode)`, sketch-fullscreen 진입, mainUI 숨김
- `'color'`: body bg 설정, mainUI 숨김, `#dev-fullscreen-exit` 버튼 표시

**`_exitDevFullscreen()` 동작:**
- `'js'`: `CanvasRunner.stop()` (viz-container 복원), mainUI 표시
- `'td'`: td-stream-monitor 닫기, mainUI 표시
- `'color'`: body bg 초기화, mainUI 표시

**CanvasRunner lifecycle (dev_mode=1):**
- `_applyDisplayMode('js')` 호출 시 → `CanvasRunner.load()` 호출하지 않음 (버튼만 표시)
- `onCanvasCode` 수신 시 → `cachedCanvasCode` 업데이트만 하고, `CanvasRunner.load()` 호출하지 않음 (guard: `if (!devMode)`)
- JS Sketch 버튼 탭 시에만 → `CanvasRunner.load(cachedCanvasCode)` 호출
- Exit 버튼 탭 시 → `CanvasRunner.stop()` 호출 → viz-container 자동 복원됨

이 설계로 dev_mode=1에서 모드 변경 시 센서 그래프가 사라지지 않는다.

**`enterTouchPad()` / `exitTouchPad()` (수정됨):**
- `enterTouchPad()`: `#main-ui` 숨김 추가 → 터치패드가 그래프 위에 투명하게 표시되던 문제 해결
- `exitTouchPad()`: `#main-ui` 복원 추가
- CSS: `#touch-pad { background: var(--bg, #0a0a0f) }` (투명 → 불투명) 도 함께 필요

**`track.onended` 안전 처리:** WebRTC 트랙이 끊길 때 이미 다른 모드(`displayMode !== 'td'`)로 전환된 상태면 배경 초기화를 스킵하여 UI 플래시 방지.

**`lastBgColor` 캐시:** `onBgColor` 수신 시 `localStorage('w2td-last-bg-color')` + 변수에 저장. `color` 모드 진입 시 즉시 적용 (TD에서 새 색이 올 때까지 검은 화면 방지).

---

### 5-10. `docs-pro/js/canvas_runner.js` — `CanvasRunner`

TD에서 내려온 JS 스케치를 `#render-canvas`에서 실행하는 샌드박스 런너.

**실행 방식:**
```javascript
const fn = new Function('canvas', 'requestFrame', 'getSensors', code);
const ret = fn(canvas, _requestFrame, getSensors);
if (typeof ret === 'function') userCleanup = ret;  // cleanup 함수 등록
```

코드 문자열에서 `canvas`, `requestFrame`, `getSensors` 세 변수를 인자로 바로 사용할 수 있다.

**`getSensors()` 반환 구조:**
```javascript
{
  ax, ay, az,           // 가속도계 m/s²
  ga, gb, gg,           // 자이로 deg/s
  oa, ob, og,           // 오리엔테이션 (ob=beta, og=gamma)
  lat, lon,             // GPS
  touch_count,          // 터치 수
  t0x, t0y, t0s,        // 첫 번째 터치 (x/y 0~1, state 1=down)
  t1x, t1y, t1s, ...    // 추가 터치들
}
```

**`requestFrame(cb)`:** rAF를 wrapping. stop() 호출 시 등록된 모든 프레임 취소.

**라이브러리 접근:** `index.html`에서 전역으로 로드된 `gsap`, `THREE`, `p5` 모두 스케치 코드 내에서 직접 사용 가능. 단 `p5`는 instance 모드만 권장 (global 모드는 충돌).

**`load(code)` 호출 시 동작:**
1. `stop()` — 기존 rAF 전부 취소, userCleanup 실행, canvas 숨김
2. `#render-canvas` 표시, 크기를 viewport × DPR로 설정
3. `new Function(...)` 으로 스케치 실행
4. 에러 발생 시 `WSClient.send({ type: 'canvas_error', message, stack })`으로 TD에 리포트

---

### 5-11. `sensor_test.js` — 스케치 예제 (Holofoil 5레이어)

센서 데이터를 시각적으로 확인하는 테스트 스케치. 관성 물리 + holofoil 효과 + 심장박동 애니메이션.

**센서 → 시각 효과 매핑:**

| 센서 | 효과 |
|------|------|
| `ax`, `ay` | 가속도 → 공 위치 관성 (스프링+댐핑) |
| `az` | 수직 가속도 → 공 크기 (위로 들면 작아짐) |
| `ob`, `og` | 오리엔테이션 → Holofoil 무지개 광택 |
| `touch` | 터치 → 심장박동 GSAP tween |

**Holofoil 5레이어 구조 (CodePen PrQKgo 스타일):**

모든 레이어는 원형 클리핑된 영역 안에서 `color-dodge` composite로 합성.

1. **좁은 무지개 빛줄기** — `linearGradient`, 기울기(`tiltX/tiltY`)로 밴드 중심·각도 이동. 밴드폭 `bw=0.04`로 매우 좁은 발광 줄기
2. **홀로그래픽 무지개 워시** — 8색 rainbow `linearGradient`, hue가 기울기로 shift
3. **회절격자 줄무늬 텍스처** — offscreen canvas 캐시(`_getHoloTexture`), 3px 가로 줄무늬, 기울기로 스크롤·회전
4. **Sparkle 반짝이** — offscreen canvas 캐시(`_getSparkleTexture`), 랜덤 점, opacity가 기울기 각도에 비례
5. **Specular highlight** — `radialGradient`, 기울기로 반사점 위치 이동

마지막에 edge vignette (source-over)로 구체감 추가.

텍스처 캐시(`_sparkleCanvas`, `_holoCanvas`)는 크기 변경 시에만 재생성. IIFE 클로저 안에서 관리.

---

### 5-12. `sensor_diagnostic.js` — 진단 스케치 (THREE.js + 2D HUD)

모든 센서 채널의 수치와 변화를 한 화면에서 확인하는 진단용 스케치.

**렌더링 구조:**

THREE.js WebGLRenderer는 offscreen canvas에 렌더링하고, CanvasRunner의 주 canvas(2D)에 `ctx.drawImage(gl, ...)` 로 합성. 같은 canvas에 WebGL + 2D 컨텍스트를 동시에 사용할 수 없기 때문에 이 패턴을 사용한다.

```javascript
const gl = document.createElement('canvas');
const renderer = new THREE.WebGLRenderer({ canvas: gl, antialias: true });
// 매 프레임:
renderer.render(scene, camera);
ctx.drawImage(gl, 0, 0, W, H);   // 3D 합성
drawHUD(s);                        // 2D 오버레이
```

**3D 씬 구성:**

| 오브젝트 | 역할 |
|---------|------|
| 폰 바디 (BoxGeometry) | `MeshPhysicalMaterial` — orientation(α/β/γ)으로 쿼터니언 회전 |
| 폰 스크린 (CanvasTexture) | 터치 포인트 + 글로우 + 가속도 크기 바 표시, 매 프레임 업데이트 |
| accel ArrowHelper | ax/ay/az 벡터 방향 시각화 |
| 자이로 링 ×3 (TorusGeometry) | Red(ga) / Green(gb) / Blue(gg) — deg/s 크기로 회전속도 표현 |

**2D HUD 패널:**

| 위치 | 내용 |
|------|------|
| 상단 패널 | Accel X/Y/Z + Gyro α/β/γ 수치 + 90샘플 스파크라인 |
| 하단 패널 | Orientation α/β/γ + 미니 컴패스 + 터치 수 + GPS 좌표 + 센서 상태 도트 |

**cleanup 함수:** renderer, 모든 geometry, material, texture 를 dispose. CanvasRunner가 스케치 교체 시 자동 호출한다.

---

## 6. TouchDesigner 파일 상세

`W2TD_BASE` 상수는 프리/프로에 따라 다르다: 프리 `'W2TD'`, 프로 `'W2TD_Pro'`. `_w2td_base()` + `_op()` 헬퍼가 베이스 COMP 기준으로 상대 경로 조회.

### 6-1. `touchdesigner[-pro]/py/callbacks.py` — Web Server DAT 콜백 (핵심)

TD의 Web Server DAT에 등록되는 메인 처리 파일.

**모듈 수준 함수 (TD가 직접 호출)**

| 함수 | 호출 시점 |
|---|---|
| `onHTTPRequest` | HTTP 요청 → `/cam_receiver.html` 은 `cam_receiver_html` Text DAT 내용 직접 서빙, 나머지는 리다이렉트 |
| `onWebSocketOpen` | WebSocket 연결 → 슬롯 할당 → ack + config 전송 |
| `onWebSocketClose` | 연결 끊김 → 슬롯 반납, sensor_table/webrtc_table 정리 |
| `onWebSocketReceiveText` | 텍스트 메시지 수신 → type별 처리 (cam_receiver와 모바일 분기) |

**수신 메시지 타입 처리 (모바일 → TD)**

| `type` | 처리 내용 |
|---|---|
| `sensor` | sensor_table 해당 슬롯 행 업데이트 + `data_ack` 응답 |
| `touch` | touch_table 업데이트 (기존 행 삭제 후 재삽입) + `data_ack` 응답 |
| `hello` | role 없음 → 로그 출력 / role=`cam_receiver` → cam_receiver 등록 (슬롯 반납 + `w2td_cam_receiver_addr_{slot}` 저장) |
| `client_name` | 기기명 수신 → sensor_table `name` + webrtc_table `name` 업데이트 |
| `screen_info` | 화면 해상도 수신 → sensor_table (css/physical/screen/dpr) + `w2td_screen_{slot}` 저장 |
| `webrtc_offer` | `webrtc_dat.openConnection` + `setRemoteDescription` + `createAnswer` + webrtc_table 행 추가 |
| `webrtc_reoffer` | 모바일-initiated 재협상 → 기존 connection으로 `setRemoteDescription` + `createAnswer` (마이크 토글 시 등) |
| `webrtc_reanswer` | TD-initiated offer에 대한 answer → `setRemoteDescription` + Audio/Video Stream Out WebRTC Track 자동 선택 (retry) |
| `webrtc_ice` | `webrtc_dat.addIceCandidate` |
| `webrtc_offer_cam` | 슬롯별 cam_receiver_addr로 `cam_offer` relay (슬롯마다 독립 cam_receiver) |
| `webrtc_ice_cam` | 슬롯별 cam_receiver로 `cam_ice` relay |
| `canvas_error` | 모바일 스케치 런타임 에러 → Textport 출력 |
| `ping` | `pong` 응답 |

**`_get_videoout(cfg)` 헬퍼 (Pro):**

config dict에서 videoout 모드를 안전하게 추출. `('Videoout', 'videoout', 'Video', 'display_mode')` 순서로 탐색하여 대소문자 불일치 문제 해결.

**신규 연결 시 자동 재전송 (on connect):**

`onWebSocketOpen` 이후 `_get_videoout(cfg)` 값에 따라 추가 데이터 자동 전송:
- `videoout == 'color'` → 저장된 배경색(`op('/').fetch('w2td_bg_color', '')`) 재전송
- `videoout == 'js'` → `_replay_canvas_code()` 호출 → 슬롯별 캐시 우선, 없으면 전체 캐시 전송

**canvas_code 관련 Python API (Pro callbacks.py):**

| 함수 | 설명 |
|---|---|
| `send_canvas_code_to_all(ws, source)` | source: Text DAT op 또는 코드 문자열. `op('/').store('w2td_canvas_code', code)` 후 전체 broadcast |
| `send_canvas_code_to_slot(ws, slot, source)` | 슬롯별 전송. `op('/').store(f'w2td_canvas_code_slot_{slot}', code)` 별도 캐시 |
| `clear_canvas_code(ws, slot=None)` | 빈 코드 전송 → CanvasRunner.stop() 트리거. slot=None이면 전체 초기화 |
| `_replay_canvas_code(ws, client_addr, slot)` | 슬롯별 캐시 우선 → 전체 캐시 순서로 재전송. 신규 연결 시 호출 |

**cam_receiver → TD 메시지 처리**

| `type` | 처리 내용 |
|---|---|
| `cam_answer` | cam_receiver의 answer → 모바일에 relay (`webrtc_answer_cam`) |
| `cam_ice` | cam_receiver의 ICE → 모바일에 relay (`webrtc_ice_cam`) |
| `cam_resolution` | 수신된 video 해상도 로그 + 슬롯별 `web_render_top_{N}` 해상도 참고 설정 |

**ack 메시지 내용 (TD → 모바일)**

`td_version` 키 포함 — TD 빌드 버전 (모바일 UI/로그용).

**Cross-DAT 상태 저장 패턴** (모듈 리로드 후 상태 유지)

```python
op('/').store('w2td_client_slots', dict)            # addr → slot 매핑
op('/').store('w2td_free_slots', list)              # 남은 슬롯
op('/').store('w2td_touch_count', dict)             # slot → touch count
op('/').store('w2td_client_names', dict)            # slot → 기기명
op('/').store(f'w2td_cam_receiver_addr_{slot}', addr)  # 슬롯별 cam_receiver WebSocket 주소
op('/').store(f'w2td_webrtc_addr_{conn_id}', addr)  # WebRTC conn_id → WS addr
op('/').store(f'w2td_webrtc_slot_to_uuid_{slot}', conn_id)  # slot → WebRTC UUID
op('/').store(f'w2td_screen_{slot}', dict)          # slot → 화면 해상도 정보
op('/').store('w2td_max_clients', int)              # 동적 최대 슬롯
```

**유용한 함수**

```python
# config 전체를 모든 클라이언트에 다시 push (w2td_config 수정 후 TD 스크립트에서 호출)
op('web_server_dat').module.broadcast_config(op('web_server_dat'))

# 특정 슬롯에 햅틱 진동 패턴 전송
op('web_server_dat').module.send_haptic_to_client(op('web_server_dat'), 1, [200, 100, 200])

# 전체 클라이언트에 햅틱 전송
op('web_server_dat').module.send_haptic_to_all(op('web_server_dat'), [200])

# CHOP 기반 햅틱 브로드캐스트 (채널명: slot1, slot2, ...)
op('web_server_dat').module.broadcast_haptic_from_chop(op('web_server_dat'))
```

---

### 6-2. `touchdesigner[-pro]/py/w2td_init.py` — Execute DAT

TD의 Execute DAT에 연결. `onCreate`에서 패키지 설치, `onStart`에서 터널/QR 생성.

**실행 흐름:**
```
onCreate()
  → install_packages()  # pip: certifi, qrcode[pil], pycloudflared, scipy

onStart()
  → _configure_ssl()   # certifi 인증서 경로 설정
  → _init_tables()     # sensor_table, touch_table, webrtc_table 초기화 + 슬롯 상태 리셋
  → _init_webrtc_ice() # w2td_config의 Turnserver 등으로 WebRTC DAT turn0* 설정
  → generate()
       → w2td_config에서 Port, Fixedurl 읽기
       → Fixedurl 있으면 그대로 사용, 없으면 pycloudflared.try_cloudflare(port)
       → op('/').store('w2td_url', url)
       → QR URL 생성: `w2td-pro.studio-edul.com/?td={host}` (Pro) / `w2td.studio-edul.com/?td={host}` (프리)
       → 베이스 COMP custom 파라미터 url에 short host 설정 (`.trycloudflare.com` 제거)
       → QR 코드 생성 → qr.png 저장
       → qr_movie_top.par.file 갱신
       → cam base URL 스토어 (`http://127.0.0.1:{port}` — cam_render_sync.py가 사용)
```

**install_packages() 설치 패키지:**

1. `certifi` (`--upgrade`) — SSL 인증서 번들 (macOS SSL 검증 실패 해결). 가장 먼저 설치.
2. `qrcode[pil]` — QR 코드 생성 + PIL
3. `pycloudflared` — Cloudflare 터널 래퍼 (첫 실행 시 cloudflared 바이너리 ~17MB 다운로드)
4. `scipy` — position estimator 등 선택 기능에서 사용

**필요 TD 노드:**

| 노드 이름 | 타입 | 용도 |
|---|---|---|
| `sensor_table` / `touch_table` | Table DAT | 센서/터치 (`_init_tables()`가 헤더 자동 세팅) |
| `webrtc_audio_container/webrtc_table` | Table DAT | WebRTC 연결 매핑 |
| `w2td_config` | Table DAT | 설정 (선택) |
| `cam_receiver_html` | Text DAT | `cam_receiver.html` 내용 (Web Server DAT이 로컬 서빙) |
| `qr_movie_top` | Movie File In TOP | QR 이미지 표시 (선택) |
| `web_server_dat` | Web Server DAT | TLS Off 기준 (`Port` 기본 9980) |
| `webrtc_audio_container/webrtc_dat` | WebRTC DAT | TURN 설정 자동 적용 |
| 베이스 COMP 자체 | COMP | Custom parameter `url` / `Url` — short host 표시 (선택) |

---

### 6-2-1. `touchdesigner-pro/py/canvas_code_dat_exec.py` — JS 스케치 자동 브로드캐스트

W2TD_Pro COMP 내부에 배치하는 DAT Execute. 외부에서 연결한 Text DAT의 내용이 바뀌면 즉시 모든 모바일에 canvas_code를 전송한다.

**TD 노드 구성:**
```
W2TD_Pro COMP 내부:
  js_code_in (In DAT)          ← COMP 외부 DAT 입력 커넥터
       ↓ (DAT Execute "DATs" 파라미터로 연결)
  canvas_code_exec (DAT Execute) ← Callbacks DAT = canvas_code_dat_exec.py

W2TD_Pro COMP 외부:
  user_sketch (Text DAT) ─────→ W2TD_Pro COMP DAT 입력
```

**동작 흐름:**
1. Text DAT 수정 → `js_code_in` 업데이트 → `onTableChange(dat)` 호출
2. `dat.text`에서 코드 추출 → `op('../web_server_dat').module.send_canvas_code_to_all(ws, code)` 호출
3. `send_canvas_code_to_all`은 코드를 `op('/').store('w2td_canvas_code', code)`에 캐시 후 전체 broadcast
4. 모바일 `CanvasRunner.load(code)` 실행 → 스케치 즉시 교체

빈 텍스트를 넣으면 `CanvasRunner.stop()` 트리거 (스케치 중단).

---

### 6-3. `touchdesigner[-pro]/py/webrtc_callbacks.py` — WebRTC DAT 콜백

`webrtc_audio_container/webrtc_dat` 노드의 Callbacks DAT에 연결.

**콜백 함수**

| 함수 | 역할 |
|---|---|
| `onOffer` | TD-initiated offer (addTrack 후) → setLocalDescription + WebSocket으로 offer 전송 |
| `onAnswer` | setLocalDescription + WebSocket으로 answer 전송 |
| `onIceCandidate` | ICE candidate를 WebSocket으로 모바일에 전달 |
| `onConnectionStateChange` | 상태 변화 → webrtc_table `state` 컬럼 업데이트. failed/closed 시 모바일에 알림 + 정리. connected 시 `webrtc_table_sync` 재실행 |
| `onIceConnectionStateChange` | ICE 상태 변화 로그 |

**헬퍼 함수**

| 함수 | 역할 |
|---|---|
| `_wt_set_state(conn_id, state)` | webrtc_table에서 conn_id 행 찾아 state 컬럼 업데이트 |
| `_send_to_client(connectionId, data)` | `w2td_webrtc_addr_{connectionId}` store 조회 → WebSocket 전송 |

---

## 7. Python 라이브러리

### 7-1. 필수 라이브러리

| 라이브러리 | 용도 | 설치 방법 |
|---------|------|----------|
| `certifi` | SSL 인증서 번들 (macOS SSL 문제 해결) | `w2td_init` onCreate 시 자동 |
| `qrcode[pil]` | QR 코드 생성 | `w2td_init` onCreate 시 자동 |
| `pycloudflared` | Cloudflare 터널 래퍼 | `w2td_init` onCreate 시 자동 |
| `scipy` | (선택) position estimator 등 | `w2td_init` onCreate 시 자동 |

### 7-2. 설치 방법

`w2td_init` Execute DAT가 프로젝트에 추가되면 onCreate에서 자동 실행. 수동 재설치:

```python
op('w2td_init').module.install_packages()
```

### 7-3. 중요 사항

- **TouchDesigner는 자체 Python 인터프리터 사용** — 시스템 Python과 별개
- 시스템 Python 설치 (`pip3 install ...`)는 TD에서 작동하지 않음
- 항상 `sys.executable` (TD의 Python) 사용하여 설치
- 새 기기에서 W2TD 설치 시 TouchDesigner 재시작 권장 (SSL 인증서 로드)

### 7-4. pycloudflared 바이너리 다운로드

- `pycloudflared`는 Python 래퍼 라이브러리
- 첫 `try_cloudflare()` 호출 시 cloudflared 바이너리 (~17MB) 다운로드
- 바이너리는 OS/아키텍처별로 다름 (macOS Intel/ARM, Windows, Linux)
- 다운로드된 바이너리는 캐시되어 이후 실행에서 재사용
- 다운로드 진행바는 `w2td_init.py`에서 `redirect_stdout`/`redirect_stderr`로 억제

---

## 8. WebSocket 메시지 전체 스펙

### 모바일 → TD

```json
{ "type": "hello" }
{ "type": "hello", "role": "cam_receiver", "slot": 1 }
{ "type": "sensor", "ax": 0.1, "ay": -0.2, "az": 9.8, "ga": 1.2, "gb": -0.5, "gg": 0.3, "oa": 270.0, "ob": 5.0, "og": -2.0, "lat": 37.5, "lon": 127.0 }
{ "type": "touch", "count": 2, "t0x": 0.25, "t0y": 0.5, "t0s": 1, "t1x": 0.75, "t1y": 0.3, "t1s": 1 }
{ "type": "client_name", "name": "iPhone 15 Pro" }
{ "type": "screen_info", "width": 390, "height": 844, "physicalWidth": 1179, "physicalHeight": 2556, "screenWidth": 390, "screenHeight": 844, "devicePixelRatio": 3.0 }
{ "type": "webrtc_offer", "sdp": "..." }
{ "type": "webrtc_reoffer", "sdp": "..." }
{ "type": "webrtc_reanswer", "sdp": "..." }
{ "type": "webrtc_ice", "candidate": "...", "sdpMLineIndex": 0, "sdpMid": "0" }
{ "type": "webrtc_offer_cam", "sdp": "...", "camType": "rear" }
{ "type": "webrtc_ice_cam", "candidate": "...", "sdpMLineIndex": 0, "sdpMid": "0", "camType": "rear" }
{ "type": "ping" }
```

> **`webrtc_reoffer`**: 모바일이 기존 WebRTC 연결에서 트랙을 추가/제거 후 재협상 (마이크 on/off 토글 등).
> **`webrtc_reanswer`**: TD-initiated offer (오디오/비디오 다운링크 addTrack 후)에 대한 모바일 answer.

### TD → 모바일

```json
{ "type": "ack", "slot": 1, "td_version": "..." }
{ "type": "rejected", "reason": "Server is currently full..." }
{ "type": "config", "sample_rate": 30, "wake_lock": 1, "haptic": 1,
  "sensor_motion": 1, "sensor_orientation": 1, "sensor_geolocation": 0,
  "sensor_touch": 1, "dev_mode": 1,
  "sensor_rear_camera": 0, "sensor_front_camera": 0, "sensor_microphone": 1,
  "audio_echo_cancellation": 0, "audio_noise_suppression": 0, "audio_auto_gain": 0,
  "show_dots": 1, "backgroundcolor": 1, "flashlight": 1, "hapticfeedback": 1,
  "audio_tx": 1, "video_tx": 1,
  "cam_resolution": "non-commercial", "camera_screenmode": "portrait" }
{ "type": "webrtc_answer", "sdp": "..." }
{ "type": "webrtc_offer", "sdp": "..." }
{ "type": "webrtc_ice", "candidate": "...", "sdpMLineIndex": 0, "sdpMid": "0" }
{ "type": "webrtc_answer_cam", "sdp": "...", "camType": "rear" }
{ "type": "webrtc_ice_cam", "candidate": "...", "sdpMLineIndex": 0, "sdpMid": "0", "camType": "rear" }
{ "type": "webrtc_state", "state": "failed" }
{ "type": "data_ack" }
{ "type": "haptic", "pattern": [200, 100, 200] }
{ "type": "haptic", "state": 1 }
{ "type": "bg_color", "color": "#FF0000", "duration": 100 }
{ "type": "flashlight", "state": 1 }
{ "type": "pong" }
```

### cam_receiver (Web Render TOP) ↔ TD

```json
/* cam_receiver → TD */
{ "type": "hello", "role": "cam_receiver" }
{ "type": "cam_answer", "slot": 1, "sdp": "...", "camType": "rear" }
{ "type": "cam_ice", "slot": 1, "candidate": "...", "sdpMLineIndex": 0, "sdpMid": "0", "camType": "rear" }
{ "type": "cam_resolution", "width": 1920, "height": 1080 }

/* TD → cam_receiver */
{ "type": "cam_offer", "slot": 1, "sdp": "...", "camType": "rear" }
{ "type": "cam_ice", "slot": 1, "candidate": "...", "sdpMLineIndex": 0, "sdpMid": "0", "camType": "rear" }
```

---

## 9. TD sensor_table 구조

| 컬럼 | 설명 |
|---|---|
| `slot` | 클라이언트 슬롯 번호 |
| `connected` | 1=연결 중 |
| `name` | 기기명 (client_name 메시지 수신 시 업데이트, 기본값: "Slot N") |
| `ax` `ay` `az` | 가속도 m/s² |
| `ga` `gb` `gg` | 자이로 deg/s |
| `oa` `ob` `og` | 방향각 deg |
| `lat` `lon` | GPS 좌표 |
| `touch_count` | 현재 터치 수 |
| `css_width` `css_height` | CSS 뷰포트 크기 (논리 픽셀) |
| `physical_width` `physical_height` | 물리 픽셀 크기 (devicePixelRatio 적용) |
| `screen_width` `screen_height` | 디바이스 화면 크기 |
| `device_pixel_ratio` | 기기 DPR (예: Retina=3.0) |

Row 0 = 헤더, Row 1~ = 슬롯 데이터 (동적 추가/삭제)

## 10. TD webrtc_table 구조

WebRTC 연결과 모바일 슬롯·기기명을 매핑하는 테이블. TD WebRTC DAT의 conn_id(내부 UUID)는 수정 불가능하므로 별도 테이블로 관리.

| 컬럼 | 설명 |
|---|---|
| `slot` | 모바일 슬롯 번호 |
| `name` | 기기명 (sensor_table과 동기화) |
| `conn_id` | WebRTC DAT 내부 UUID (e.g. `b33d0dc8-4015-4a5d-aa97-a4e5447b5e93`) |
| `state` | 연결 상태 (`connecting` → `connected` / `failed` / `closed`) |

- Row 0 = 헤더
- WebRTC offer 수신 시 행 추가 (`connecting`)
- `onConnectionStateChange` 콜백에서 state 업데이트
- 모바일 WebSocket 종료 시 행 삭제

---

## 11. 카메라 WebRTC 흐름

카메라 WebRTC는 마이크(단일 TD WebRTC DAT)와 달리, **슬롯마다 별도 Web Render TOP + cam_receiver.html**로 처리. 슬롯 단위로 독립 PeerConnection.

```
모바일 슬롯 N → TD (callbacks.py)
   ↓ relay
cam_receiver.html (web_render_top_{N}, WebSocket 자체 연결)
   ↑___________________________________________↓
           offer/answer/ICE relay (TD 중계)
```

**시그널링 흐름 (카메라 활성화)**

```
모바일: getUserMedia({ video: true })
  → RTCPeerConnection 생성
  → createOffer
  → WSClient.send({ type:'webrtc_offer_cam', sdp, camType:'rear' })

TD callbacks.py:
  webrtc_offer_cam 수신 → w2td_cam_receiver_addr_{slot}로 cam_offer relay

cam_receiver.html (web_render_top_{N} 내부):
  cam_offer 수신 → RTCPeerConnection 생성
  → setRemoteDescription(offer)
  → createAnswer
  → WS.send({ type:'cam_answer', slot, sdp, camType:'rear' })
  → ICE candidates 교환

TD callbacks.py:
  cam_answer → 해당 슬롯 모바일로 webrtc_answer_cam relay
  cam_ice    → 해당 슬롯 모바일로 webrtc_ice_cam relay

모바일:
  webrtc_answer_cam 수신 → setRemoteDescription
  ICE 교환 완료 → P2P 카메라 스트림 시작
```

**cam_receiver.html 서빙 방식**

- TD Web Server DAT `onHTTPRequest`에서 `/cam_receiver.html` 요청 감지
- `cam_receiver_html` Text DAT 내용을 직접 HTTP 응답으로 반환 (디스크 파일 아님 — TOE 안에 내장)
- GitHub Pages 없이 TD 안에서 완결 → mixed-content 문제 없음
- `cam_render_sync.py`가 슬롯마다 `web_render_top_{N}` 생성 시 url = `http://127.0.0.1:{port}/cam_receiver.html?slot={N}&port={port}`

**cam_receiver.html 기능**

- URL 쿼리 `slot` 파싱 후 WebSocket hello 시 `{ role:'cam_receiver', slot: N }` 전송 → TD가 슬롯별 cam_receiver 등록
- 해당 슬롯 모바일의 offer만 수신 (TD가 slot 매칭 후 relay)
- 후면/전면 카메라 각각 별도 RTCPeerConnection (`peerKey(slot, camType)`)
- 두 video 엘리먼트 (rear/front) — 상호배타
- `ontrack` → `onloadedmetadata` → `srcObject` → 명시적 `play()` (Chromium autoplay 정책 대응)
- video 해상도 수신 시 `cam_resolution` 메시지로 TD에 전달

---

## 12. dev_mode 동작

| dev_mode | UI 형태 | 센서 활성화 방식 |
|---|---|---|
| `1` (개발/전시자용) | 풀 UI (센서목록, 그래프, 브로드캐스트 바) | Enable Sensors 버튼 탭 |
| `0` (사용자/전시용) | 풀스크린 터치패드만 | 첫 터치 시 자동 (iOS는 TAP TO START 버튼) |

`localStorage('w2td-dev-mode')` 에 캐시 → 다음 접속 시 플래시 없이 즉시 적용.

---

## 13. iOS 권한 처리 특이사항

- `DeviceMotionEvent.requestPermission()` — **직접적인 user gesture** 에서만 가능
- `getUserMedia()` — user gesture 직후 async 체인에서 호출 가능 (iOS 15+)
- dev_mode=1: Enable Sensors 버튼 탭 → `requestPermissions()` 호출
- dev_mode=0: TAP TO START 버튼 탭 → `requestPermissions()` 호출
- 마이크: Microphone 항목 탭 → `getUserMedia()` 호출

---

## 14. 주요 수정 가이드

### config 키 추가하기

1. `callbacks.py` `_config_msg()` 에 키 추가
2. `app.js` `applyConfig()` 에 처리 로직 추가
3. `w2td_config` Table DAT에 행 추가 (TD에서)

### 새 메시지 타입 추가하기

1. 모바일 → TD: `websocket.js`의 `send()` 또는 새 sendXxx() 함수, `callbacks.py` `onWebSocketReceiveText` 에 elif 추가
2. TD → 모바일: `callbacks.py`에서 `webSocketSendText()`, `websocket.js` `onmessage` 에 라우팅 추가, `app.js`에 처리 로직 추가

### 센서 목록에 새 항목 추가하기

`app.js` `renderSensorList()` 내부에서 `els.sensorList.appendChild(li)` 패턴 따라 추가. CSS 클래스: `available selected/deselected` 또는 `unavailable`.

---

## 14-0-1. webrtc_video_sync.py DAT Execute 설정 주의사항

`webrtc_video_container` 안의 DAT Execute가 **두 DAT 모두**를 감시해야 한다:

| DATs 파라미터 항목 | 이유 |
|---|---|
| `webrtc_table` (or `../webrtc_audio_container/webrtc_table`) | 클라이언트 연결/해제 시 노드 생성/삭제 |
| `../../w2td_config` | `Videoout` 값이 바뀔 때 (`none` → `td` 등) 이미 연결된 클라이언트에 대해서도 즉시 노드 생성 트리거 |

`w2td_config`를 누락하면 `Videoout=td`로 설정을 바꿔도 클라이언트가 이미 연결된 상태에서는 sync()가 호출되지 않아 video TX 노드가 생성되지 않는다.

---

## 14-1. WebRTC 오디오 다운링크 (TD → 모바일) 추가하기

TD에서 모바일로 실시간 오디오를 스트리밍하는 기능. `w2td_audio_bus` CHOP의 슬롯별 채널을 개별 모바일 기기에 전송.

**필요 TD 노드:**

| 노드 이름 | 타입 | 용도 |
|---|---|---|
| `w2td_audio_bus` | Constant CHOP | 채널: `slot1`, `slot2`, ... — 슬롯별 오디오 신호 입력 |
| `webrtc_audio_container` | Base COMP | RX/TX CHOP 자동 생성 컨테이너 (webrtc_table_sync.py가 관리) |

**자동 생성되는 노드 (webrtc_table_sync.py):**

| 노드 | 타입 | 설명 |
|---|---|---|
| `select_slot{N}` | Select CHOP | `w2td_audio_bus`에서 `slotN` 채널만 선택 |
| `webrtc_audio_out_{N}` | Audio Stream Out CHOP | WebRTC 모드, 해당 conn_id에 연결 |

**핵심 개념:**
- Select CHOP은 `w2td_audio_bus`의 모든 채널 중 해당 슬롯 채널만 골라서 전달 → 각 클라이언트가 자신의 채널만 수신
- Audio Stream Out CHOP은 기본 RTSP 모드 → 반드시 `webrtc` 모드로 설정
- **`webrtcDAT.addTrack(conn_id, 'audio_out_{slot}', 'audio')` 호출 필수** — 이 없이는 webrtctrack 메뉴가 비어있음
- `addTrack()` + `createOffer()` 순서로 호출 (`delayFrames=3`으로 CHOP cook 대기)
- `webrtc_reanswer` 수신 후 retry 메커니즘 (delayFrames=5, 최대 15회)으로 `webrtctrack = 'audio_out_{slot}'` 자동 선택

---

## 14-2. 배경색 제어 (bg_color) — background_chop_exec.py

TD에서 모바일 기기 배경색을 제어하는 CHOP Execute DAT 스크립트.

**설정:**
1. CHOP Execute DAT 생성
2. "CHOPs" 파라미터: `w2td_background w2td_bg_color_bus` (공백 구분)
3. "Value Change" 활성화
4. `background_chop_exec.py` 내용 붙여넣기

**Mode 1 — 전체 브로드캐스트 (`w2td_background` 또는 `w2td_color`):**

| 속성 | 값 |
|---|---|
| CHOP 이름 | `w2td_background` 또는 `w2td_color` (둘 다 인식) |
| 채널 | `r`, `g`, `b` (0~1 범위, 샘플 1개) |
| 효과 | 모든 연결된 기기에 동일 색상 전송 |

**Mode 2 — 슬롯별 개별 제어 (`w2td_bg_color_bus`):**

| 속성 | 값 |
|---|---|
| CHOP 이름 | `w2td_bg_color_bus` |
| 채널 | `slot1_r`, `slot1_g`, `slot1_b`, `slot2_r`, `slot2_g`, `slot2_b`, ... (0~1 범위) |
| 채널 매핑 | `slot{N}_r/g/b` → 슬롯 N |
| 효과 | 각 슬롯에 해당 색상만 전송 |

**채널 구성 예 (Merge CHOP 등으로 조합):**
슬롯별 Constant CHOP (r, g, b) → Rename CHOP으로 `slot{N}_r/g/b` 변경 → Merge CHOP → 이름 `w2td_bg_color_bus`.

**웹 메시지:**
- `{ "type": "bg_color", "color": "#ff0000", "duration": 0 }`
- `duration > 0` 이면 해당 ms 후 자동으로 원래 배경색으로 복원 (플래시/스트로브 효과)

**레이어 우선순위:**
- `bg_color`는 `document.body.style.backgroundColor`와 `#touch-pad` 배경에 적용
- TD 비디오 다운링크(`#webrtc-td-stream`)는 z-index:501로 배경색 위에 렌더링됨
- 즉 비디오가 활성화되어 있으면 배경색이 비디오에 가려짐

---

## 15. 알려진 제한사항

| 항목 | 내용 |
|---|---|
| Video Stream In TOP | TD Pro 라이센스 전용 → Camera 항목은 UI에 표시되지만 비활성 |
| cloudflared URL | TD 재시작마다 URL 변경 → QR 재스캔 필요 |
| 마이크 권한 거부 시 | 팝업 없이 조용히 실패 → 브라우저 설정에서 수동 허용 필요 |
| GitHub Pages HTTPS | ws:// 불가, 반드시 wss:// (cloudflared 필수) |
| 로컬 IP 직접 접속 | GitHub Pages에서 mixed content 차단 → cloudflared 필수 |

---

## 16. 마이크 오디오 처리 설정 (TD에서 제어)

브라우저 `getUserMedia`의 오디오 처리 옵션을 w2td_config로 제어할 수 있다. **w2td_config Table DAT**에 아래 행을 추가하고, 값을 바꾼 뒤 `broadcast_config`를 호출하면 연결된 클라이언트에 즉시 반영된다. (마이크가 이미 켜져 있으면 자동 재연결됨)

| w2td_config 키 | 값 | 효과 |
|---|---|---|
| `audio_echo_cancellation` | 0 | 에코 제거 끔 — 원본 신호, 스피커→마이크 피드백 가능 |
| | 1 | 에코 제거 켜짐 — 스피커 소리 제거 |
| `audio_noise_suppression` | 0 | 노이즈 억제 끔 — 타이핑·배경음 모두 수집 |
| | 1 | 노이즈 억제 켜짐 — 음성 구간만 강조 |
| `audio_auto_gain` | 0 | 자동 게인 끔 — 입력 그대로 |
| | 1 | 자동 게인 켜짐 — 음량 자동 보정 |

**설정 절차**

1. TD에서 `w2td_config` Table DAT 열기
2. 열 구조: `key` | `value`
3. 아래처럼 행 추가 (없는 것만):

   | key | value |
   |-----|-------|
   | audio_echo_cancellation | 0 |
   | audio_noise_suppression | 0 |
   | audio_auto_gain | 0 |

4. **원본 신호** (타이핑, 배경음 수집): 위 세 값 모두 `0`
5. **음성 위주** (노이즈 제거): `audio_noise_suppression` = 1 등
6. 값 변경 후 적용:
   ```python
   op('web_server_dat').module.broadcast_config(op('web_server_dat'))
   ```
   (또는 Execute DAT, Button DAT 등에서 실행)

---

## 17. 문제 해결 가이드

### 17-1. SSL 인증서 문제 (macOS)

**증상:** Cloudflare 터널이 SSL 인증서 검증 오류로 실패, 로컬 IP로 폴백

**에러 메시지:**
```
[W2TD] Cloudflare tunnel failed: <urlopen error [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: unable to get local issuer certificate>
```

**해결 방법:**

1. `certifi` 재설치:
   ```python
   op('w2td_init').module.install_packages()
   ```

2. certifi 설치 확인:
   ```python
   import certifi
   print(certifi.where())
   # 출력 예: /Applications/TouchDesigner.app/.../certifi/cacert.pem
   ```

3. 설치 후 TouchDesigner 재시작

4. SSL 설정 로그 확인:
   ```
   [W2TD] SSL certificates configured: /Applications/.../certifi/cacert.pem
   ```

**작동 원리:**
- `w2td_init.py`가 시작 시 SSL 인증서를 자동으로 설정
- 환경 변수 설정: `SSL_CERT_FILE`, `REQUESTS_CA_BUNDLE`
- Python의 기본 SSL 컨텍스트를 certifi 사용하도록 설정
- 다른 기기에서도 작동 — `certifi.where()`가 자동으로 올바른 경로 찾음

### 17-2. 마이크 문제

**증상: 권한 팝업이 뜨지 않고 마이크가 활성화되지 않음**

**원인**: 브라우저가 해당 도메인의 마이크 권한을 이미 "거부"로 기억하고 있어 조용히 실패.

**해결 방법 (사용자)**

| 브라우저 | 방법 |
|---|---|
| iOS Safari | 설정 → Safari → 마이크 → studio-edul.github.io → 허용 |
| Android Chrome | 주소창 자물쇠 아이콘 → 권한 → 마이크 → 허용 |
| 데스크톱 Chrome | 주소창 자물쇠 → 이 사이트 권한 → 마이크 → 허용 |

**코드 측 동작**: 권한 거부 시 `NotAllowedError` 포착 → 로그 패널에 안내 메시지 표시.

**증상: config `sensor_microphone=1`로 설정했는데 실제 연결이 안 됨**

- config auto-start (`_startWebRTC`)는 WebSocket 메시지 핸들러에서 호출 → **iOS에서 user gesture 없이 getUserMedia 불가** → 조용히 실패
- UI는 초록(micEnabled=true)으로 표시되지만 실제 스트림 없음
- 사용자가 Microphone 항목을 직접 탭해서 활성화해야 함

**증상: WebRTC DAT에 연결된 기기가 안 뜸 — 로그 확인**

**웹 로그 확인** (로그 보기 버튼):
- `WebRTC getUserMedia OK` → 마이크/카메라 획득 성공
- `WebRTC Offer sent to TD` → offer 전송 성공
- `WebRTC Offer FAILED — WebSocket not connected` → **WebSocket 미연결**, TD 연결 후 마이크 다시 시도
- `WebRTC Answer received from TD` → TD에서 answer 수신됨
- `WebRTC iceConnectionState: connected` → P2P 연결 완료
- `WebRTC connectionState: failed` → 연결 실패 (방화벽, ICE 등)

**TD 로그 확인** (Textport):
- `[W2TD WebRTC] Offer received from slot 1` → offer 수신됨
- `[W2TD WebRTC] Answer sent to connectionId=1` → answer 전송됨
- 위 로그가 없으면 → `webrtc_dat` Callbacks DAT 미연결 또는 callbacks.py의 webrtc_offer 처리 문제

- **TD: offer 받은 직후 Disconnected** → WebRTC connectionId 오류였을 수 있음. callbacks.py에서 `openConnection()`으로 UUID 생성 후 사용하도록 수정됨.

- **STUN URL 확인**: TD WebRTC DAT의 STUN이 `stun:stun.l.google.com:19302` 인지 확인 (오타: `stun.1` ❌ → `stun.l` ✓)

**toggle 로직 설계 원칙**

`handleMicToggle`의 toggle 방향은 **`micEnabled`** (사용자 의도) 기준으로 결정.
`WebRTCModule.isMicActive()` (실제 스트림 상태)를 기준으로 하면 config auto-start 실패 상태에서 방향이 반전되는 버그 발생.

```
micEnabled=true  → 탭 → DISABLE 경로 (stop + micEnabled=false)
micEnabled=false → 탭 → ENABLE 경로  (start + getUserMedia)
```

---

## 18. 이 문서 업데이트 방법

새 기능 추가·버그 수정 후 이 파일에 반영:

1. **새 기능 추가 시**: 해당 파일 섹션(5.x ~ 6.x)에 함수·메서드 설명 추가, 필요 시 섹션 신설
2. **config 키 변경/추가 시**: 섹션 4(Config 시스템 표) + 섹션 8(메시지 스펙) 업데이트
3. **새 WebSocket 메시지 타입**: 섹션 8(메시지 스펙) 업데이트
4. **TD 노드 변경 시**: 섹션 6(TouchDesigner 파일) + 관련 노드 표 업데이트
5. **알려진 버그/제한사항**: 섹션 13~15 업데이트

> 다른 채팅 세션에서 개발 시작 시 이 문서를 먼저 읽고, 작업 완료 후 관련 섹션을 업데이트할 것.

---

## 19. 추가 파일

### 19-1. `touchdesigner[-pro]/py/webrtc_table_sync.py` — WebRTC CHOP/TOP 동기화

`webrtc_audio_container/webrtc_table` 변경 시 Audio Stream In/Out CHOP + Video Stream Out TOP을 자동 생성·삭제·연결하는 스크립트.

**설정:**
1. DAT Execute DAT 생성 (`webrtc_audio_container` 내)
2. "DATs" 파라미터를 `webrtc_table`로 설정
3. "Table Change" 체크박스 활성화
4. `webrtc_table_sync.py` 내용 연결

**RX (수신) — 마이크 업링크:**
- 슬롯별 `webrtc_audio_{N}` Audio Stream In CHOP 생성 (`webrtc_audio_container` 내)
- WebRTC DAT + connection 파라미터 자동 설정
- 연결 끊긴 슬롯의 CHOP 자동 삭제

**TX (송신) — 오디오 다운링크 (Pro):**
- `w2td_audio_bus` CHOP이 존재하면 활성화
- 슬롯별 `select_slot{N}` Select CHOP → `webrtc_audio_out_{N}` Audio Stream Out CHOP (WebRTC 모드)
- `addTrack(conn_id, 'audio_out_{slot}', 'audio')` 호출 후 createOffer
- `webrtc_reanswer` 수신 후 retry (delayFrames=5, 최대 15회)로 `webrtctrack = 'audio_out_{slot}'` 자동 선택

**TX (송신) — 비디오 다운링크 (Pro) → `webrtc_video_sync.py`로 분리됨:**
- 비디오 TX 노드 관리는 `webrtc_video_container` 안의 `webrtc_video_sync.py`가 담당 (별도 DAT Execute)
- `webrtc_table` 변경 감지 → `select_video_slot{N}` → `flip_top_{N}` → `video_stream_out_{N}` 자동 생성/삭제
- `addTrack(video)` + `createOffer` delayFrames=5 (오디오 addTrack frame=3 이후)
- `w2td_config`의 `Video`/`Videoout` 키로 활성화 여부 판단 (`_read_video_tx_enabled()`)

**createOffer 타이밍 (오디오+비디오 순차):**
1. `webrtc_table_sync.py`: `addTrack(audio)` + `createOffer` at delayFrames=3
2. `webrtc_video_sync.py`: `addTrack(video)` + `createOffer` at delayFrames=5 (audio 이후)

**TD에서 오디오 다운링크 사용법:**
1. `w2td_audio_bus` Constant CHOP 생성 (채널명: `slot1`, `slot2`, ...)
2. 오디오 신호를 해당 채널에 연결
3. 모바일 WebRTC 연결 시 자동으로 TX 노드 생성 + 스트리밍 시작

**TD에서 비디오 다운링크 사용법:**
1. 베이스 COMP 밖 (`project1`)에 `video_slot{N}` TOP 배치 (임의 TOP — Movie File In, Render TOP 등)
2. `webrtc_video_container` 안에 DAT Execute 생성:
   - Callbacks DAT: `webrtc_video_sync`
   - DATs: `webrtc_table` (같은 컨테이너) 또는 `../webrtc_audio_container/webrtc_table`
   - Table Change: On
3. 모바일 WebRTC 연결 시 자동으로 `select_video_slot{N}` → `flip_top_{N}` → `video_stream_out_{N}` 생성
4. dev_mode=1 모바일: "TD Stream" 버튼으로 전체화면 확인
5. dev_mode=0 모바일: 풀스크린 배경으로 자동 표시 (touch-pad 뒤, z-index:501)

---

### 19-2. `touchdesigner[-pro]/py/cam_render_sync.py` — 카메라 수신 파이프라인

`sensor_table` 변경을 감시하여 연결된 슬롯마다 `webrtc_video_container` 내에 카메라 수신 파이프라인을 자동 생성.

**자동 생성 체인 (슬롯 N 연결 시):**
```
web_render_top_{N}  (cam_receiver.html 로드, url 쿼리로 slot/port 전달)
  → transform_top_{N}  (Screenmode=Landscape일 때 rotate -90°)
  → crop_top_{N}  (카메라 해상도 기준 crop — 정사각 → 세로/가로 비율 컷)
  → video_received_slot{N}  (Null TOP — 외부 참조 포인트)
  → layout1  (Layout TOP — 모든 슬롯 컴포지트, 슬롯 1개 이상 연결 시 자동 생성)
```

**주요 동작:**
- 슬롯 연결 시 파이프라인 생성, 연결 끊기면 삭제
- 모든 슬롯 disconnect 시 `layout1` 자체 삭제
- Resolution/Screenmode 변경은 `config_watch.py`가 web_render_top/transform/crop 파라미터 업데이트

**외부 참조:** 다른 네트워크에서 슬롯별 카메라 영상을 쓰려면 `W2TD_Pro/webrtc_video_container/video_received_slot{N}` null TOP을 참조.

---

### 19-3. `touchdesigner[-pro]/py/config_watch.py`

`w2td_config` Table DAT 변경 시 자동으로 config 브로드캐스트 + 슬롯별 파이프라인 파라미터 업데이트.

**설정:**
1. DAT Execute DAT 생성 (이름: `config_watch`)
2. "DATs" 파라미터 = `w2td_config`
3. "Table Change" 체크박스 활성화

**동작:**
- 변경 감지 → 300ms 디바운스 → `_do_broadcast()` 실행
- `_build_config_msg(cfg)`: 모든 config 키를 JSON으로 변환. `videoout` 필드는 `('Videoout', 'videoout', 'Video', 'display_mode')` 순서로 fallback 탐색
- 모든 연결된 클라이언트에 `config` 메시지 전송. `op('/').fetch('w2td_client_slots')` → `webSocketSendText()`. stale addr는 자동 건너뜀
- Resolution/Screenmode 변경 시 `web_render_top_{N}` 해상도 + `transform_top_{N}` rotate + `crop_top_{N}` crop 자동 재설정
- `videoout=js` + `Jsfile` 설정 시: 파일을 `open()`으로 직접 읽어 `canvas_code` 메시지로 전체 전송 (module 접근 없이 self-contained)
- Audio/Video 키 변경 시 `webrtc_table_sync.sync()` 재실행 (TX 노드 추가/제거)

---

### 19-3-1. `touchdesigner-pro/py/webrtc_video_sync.py` — 비디오 TX 파이프라인 (신규)

`webrtc_table` 변경 시 `webrtc_video_container` 안에 비디오 TX 노드를 자동 생성/삭제하는 독립 스크립트. `webrtc_table_sync.py`에서 비디오 TX 로직을 분리.

**설정:**
1. `webrtc_video_container` 안에 DAT Execute DAT 생성
2. Callbacks DAT: `webrtc_video_sync`
3. DATs: `webrtc_table` (같은 컨테이너 안 또는 `../webrtc_audio_container/webrtc_table`)
4. Table Change: On

**생성되는 노드 체인:**
```
select_video_slot{N}  →  flip_top_{N}  →  video_stream_out_{N}
```
- `select_video_slot{N}`: `../../video_slot{N}` 참조 (webrtc_video_container → W2TD_Pro → project1)
- `video_stream_out_{N}`: WebRTC 모드, `webrtc_dat` + `conn_id` 자동 설정

**타이밍:**
- `addTrack(video)` + `createOffer` at `delayFrames=5` — `webrtc_table_sync.py`의 `addTrack(audio)` (frame=3) 이후 실행
- `BLOCK_HEIGHT=300`, `CAM_ROW_H=150` — `cam_render_sync.py`와 반드시 동일 유지

**`_read_video_tx_enabled()` 로직:**
- `w2td_config`에서 `Video` 또는 `Videoout` 키 탐색
- 정수 값 → `bool(int(val))`, 문자열 값(`td`, `js`, `color`) → `'none'`/`'0'`/`'false'` 아닌 한 활성화

---

### 19-4. `touchdesigner-pro/py/haptic_chop_exec.py` / `flashlight_chop_exec.py`

Pro 전용 CHOP Execute DAT 스크립트. CHOP 채널 값이 바뀔 때 모바일에 메시지 전송.

| 스크립트 | 타겟 CHOP | 채널 | 메시지 |
|---|---|---|---|
| `haptic_chop_exec.py` | `w2td_haptic` | `slot1`, `slot2`, ... / `all` | `{ type:'haptic', state: 0\|1 }` |
| `flashlight_chop_exec.py` | `w2td_flashlight` | `slot1`, `slot2`, ... / `all` | `{ type:'flashlight', state: 0\|1 }` |

**설정 (동일):**
1. CHOP Execute DAT 생성
2. "CHOPs" 파라미터에 타겟 CHOP 이름
3. "Value Change" 활성화
4. 스크립트 연결
5. 값 > 0.5 → state=1, 이하 → state=0 (`val != prev` 조건)

채널 이름 `slot{N}` → 해당 슬롯, `all` → 전체 브로드캐스트. 기타 채널명은 무시.

---

### 19-5. `touchdesigner-pro/py/w2td_zombie_checker.py` / `update_execs.py`

- **`w2td_zombie_checker.py`**: 주기적으로 `w2td_client_slots`와 `webSocketConnections`를 비교해 좀비 슬롯 정리 (CHOP Execute / Timer 등에 연결)
- **`update_execs.py`**: 콜백 DAT들 (callbacks, webrtc_callbacks, config_watch 등)의 스크립트 링크를 일괄 재연결하는 유틸리티 (TOE 버전업 시 사용)

---

### 19-6. `touchdesigner-examples/2026_korail/code/line_chop.py` — 센서 활성 판별

Script CHOP. `sensor_table`에서 연결된 슬롯을 수집해 속도를 시간 적분하여 슬라이딩 윈도우 출력.

**센서 활성 판별 로직 (connected_slots 수집 시)**

기존에는 `az` 단일 값이 0에 가까우면 센서 미활성으로 판단했으나, 디바이스를 세워서 들고 있는 경우 `az ≈ 0`이라도 센서가 활성 상태일 수 있어 신뢰도가 낮았다.

현재는 `az`, `ga`, `gb`, `gg` 네 축을 동시에 체크하여 **모두 0.1 미만일 때만** 미활성으로 판단한다:

```python
sensor_axes = ('az', 'ga', 'gb', 'gg')
if not any(col in st_h and abs(float(st[row, st_h[col]])) > 0.1 for col in sensor_axes):
    continue  # 센서 미활성 — 선 그리기 시작 안 함
```

센서가 실제로 비활성화 상태라면 네 축 전부 0이다. 활성 상태라면 자이로(ga/gb/gg) 중 최소 하나가 움직임이나 중력 성분을 반영한다.

**`visibility` 메시지와의 연계**

모바일이 백그라운드로 나가면 `callbacks.py`가 `sensor_table`의 ax/ay/az/ga/gb/gg를 0으로 초기화한다. 이때 위 센서 판별 조건에도 걸리므로 `connected_slots`에서 해당 슬롯이 제외되고, `active_slots`에도 포함되지 않아 선이 더 이상 진행하지 않는다. 슬롯은 `inactive` 마킹되지 않고 유지되어, 모바일이 포그라운드로 돌아오면 센서 데이터가 재수신되는 즉시 자동으로 선이 재개된다.
