# W2TD (Web-to-TouchDesigner Bridge) 개발 문서

> 최종 업데이트: 2026-03-02 (Resolution/Screenmode 카메라 설정, w2td_init URL 설정 개선)
> 목적: 추후 세션에서 파일 위치·구현 방식을 빠르게 파악하기 위한 참고 문서

---

## 1. 프로젝트 개요

모바일 브라우저의 센서 데이터(가속도계·자이로·GPS·터치)와 마이크를 WebSocket으로 TouchDesigner에 실시간 전송하는 브리지.

```
Mobile Browser (GitHub Pages HTTPS)
  └─ WebSocket (wss://)
       └─ cloudflared 터널 (https://xxxx.trycloudflare.com)
            └─ TD Web Server DAT (port 9980, TLS OFF)
                 └─ callbacks.py → sensor_table / touch_table
```

---

## 2. 빠른 시작 가이드

### 2-1. 초기 설정 (기기당 1회)

**1단계: Python 패키지 설치**

TouchDesigner Textport 또는 Button DAT에서:
```python
op('w2td_setup').module.install()
```

설치되는 패키지:
- `certifi` (SSL 인증서, macOS에서 특히 중요)
- `qrcode[pil]` (QR 코드 생성)
- `pycloudflared` (Cloudflare 터널)

**2단계: TouchDesigner 재시작**

설치 후 TD를 재시작하여 SSL 인증서가 제대로 로드되도록 합니다.

### 2-2. TouchDesigner 프로젝트 설정

**필수 DAT:**

| 노드 이름 | 타입 | 용도 |
|-----------|------|------|
| `web_server_dat` | Web Server DAT | WebSocket + HTTP 연결 수신 |
| `callbacks` | Text DAT | Web Server DAT의 Callbacks Script에 설정 → `callbacks.py` 내용 붙여넣기 |
| `w2td_init` | Execute DAT | `w2td_init.py`로 설정 → TD 시작 시 실행 |
| `sensor_table` | Table DAT | `init_tables()`에서 자동 생성 |
| `touch_table` | Table DAT | `init_tables()`에서 자동 생성 |
| `webrtc_table` | Table DAT | WebRTC 연결 매핑 (slot/name/conn_id/state) |
| `webrtc_dat` | WebRTC DAT | 마이크 WebRTC 연결. Callbacks DAT = `webrtc_callbacks` |
| `webrtc_callbacks` | Text DAT | `webrtc_callbacks.py` 연결. WebRTC DAT Callbacks DAT 파라미터에 설정 |
| `webrtc_audio_1` | Audio Stream In CHOP | Protocol=WebRTC, WebRTC DAT=`webrtc_dat` |
| `web_render_top` | Web Render TOP | 카메라 수신용. URL은 `w2td_init.py`가 자동 설정 |
| `w2td_config` | Table DAT | 선택사항 — 설정값 오버라이드 |
| W2TD base comp | COMP | 선택사항 — par.url 또는 url_text로 QR URL 표시 |
| `qr_movie_top` | Movie File In TOP | 선택사항 — QR 코드 이미지 표시 |

**Web Server DAT 설정:**
- Active: `On`
- Port: `9980`
- TLS: `Off` (cloudflared 필수)

**Execute DAT (`w2td_init`) 설정:**
- Script: `w2td_init.py` 내용
- Run on: `OnStart`

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
- `certifi` 설치 확인: `op('w2td_setup').module.install()`
- 설치 후 TouchDesigner 재시작

**QR 코드가 cloudflare URL 대신 로컬 IP 표시:**
- SSL 인증서 문제 (macOS에서 흔함) — 섹션 17 참조
- Textport 로그에서 `[W2TD] SSL certificates configured` 메시지 확인

---

## 3. 파일 구조 전체 맵

```
Integrated-Web-to-TouchDesigner-Bridge/
├── docs/                          ← GitHub Pages 배포 (HTTPS)
│   ├── index.html                 ← HTML 뼈대 + 스크립트 로드 순서
│   ├── css/
│   │   └── style.css              ← 다크 테마, 모바일 최적화 CSS
│   └── js/
│       ├── websocket.js           ← WebSocket 연결 관리
│       ├── sensors.js             ← 센서 감지·권한·데이터 수집
│       ├── touch.js               ← 멀티터치 추적·정규화
│       ├── visualization.js       ← Canvas 스파크라인 그래프 + 터치 시각화
│       ├── webrtc.js              ← WebRTC 피어 연결·마이크 스트림
│       └── app.js                 ← 전체 조율 컨트롤러 (메인 앱)
│
├── touchdesigner/
│   ├── py/
│   │   ├── callbacks.py           ← TD Web Server DAT 콜백 (메인)
│   │   ├── w2td_init.py            ← TD Execute DAT onStart: cloudflared 터널 + QR 코드
│   │   ├── w2td_setup.py           ← 최초 1회 pip 패키지 설치
│   │   ├── webrtc_callbacks.py    ← TD WebRTC DAT 콜백 (마이크 시그널링)
│   │   ├── config_watch.py        ← w2td_config 변경 시 자동 브로드캐스트
│   │   ├── cam_render_sync.py     ← Web Render TOP 동기화 (sensor_table 기반)
│   │   └── webrtc_table_sync.py   ← Audio Stream In CHOP 동기화
│   ├── cam_receiver.html          ← Web Render TOP용 카메라 수신 페이지 (TD 로컬 서빙)
│   └── position_estimator.py      ← 상대 위치 추정 (선택사항, numpy 필요)
│
├── DEV_DOCS.md                    ← 이 파일
└── MEMORY.md                      ← Claude 자동 기억 파일
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

TD의 `w2td_config` Table DAT에서 값을 읽어 연결 시 모바일로 push.

| w2td_config 키 | 기본값 | 설명 |
|---|---|---|
| `sample_rate` | 30 | 브로드캐스트 Hz |
| `wake_lock` | 1 | 화면 잠금 방지 |
| `haptic` | 1 | 진동 피드백 |
| `sensor_motion` | 1 | 가속도+자이로 활성화 |
| `sensor_orientation` | 1 | 방향각 활성화 |
| `sensor_geolocation` | 0 | GPS 활성화 |
| `sensor_touch` | 1 | 터치 활성화 |
| `dev_mode` | 1 | 1=풀 UI, 0=터치패드만 |
| `sensor_rear_camera` | 0 | 후면 카메라 WebRTC 활성화 |
| `sensor_front_camera` | 0 | 전면 카메라 WebRTC 활성화 |
| `sensor_microphone` | 0 | 마이크 WebRTC 자동활성화 |
| `audio_echo_cancellation` | 0 | 에코 제거 (0=끔/원본, 1=켜짐) |
| `audio_noise_suppression` | 0 | 노이즈 억제 (0=끔/원본, 1=켜짐) |
| `audio_auto_gain` | 0 | 자동 게인 (0=끔/원본, 1=켜짐) |
| `ice_servers` | (없음) | 다른 네트워크용 TURN. JSON 배열 (예: `[{"urls":"turn:..."}]`) |
| `ice_transport_policy` | (없음) | `relay` = TURN만 사용 (터널/다른 네트워크 시 강제) |
| `max_clients` | 20 | 최대 접속 수 |
| `Resolution` | Non-Commercial | 카메라 해상도: `Non-Commercial`(540×960), `FHD`(1920×1080), `4K`(3840×2160) |
| `Screenmode` | Portrait | 카메라 방향: `Portrait`(세로), `Landscape`(가로) |

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
msg.type === 'ack'            → onStatusChange('connected')
msg.type === 'config'         → onConfig(msg)
msg.type === 'webrtc_answer'  → onWebRTCSignal(msg)
msg.type === 'webrtc_ice'     → onWebRTCSignal(msg)
msg.type === 'webrtc_state'   → onWebRTCSignal(msg)
msg.type === 'rejected'       → onStatusChange('rejected'), 재연결 중단
```

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

**카메라 해상도/화면모드**: config의 `camera_resolution`, `camera_screenmode`로 제어.
- Resolution: `Non-Commercial`(540×960), `FHD`(1920×1080), `4K`(3840×2160)
- Screenmode: `Portrait`(세로), `Landscape`(가로) — Portrait일 때 height > width

**ICE 서버**: Google STUN × 2 + openrelay.metered.ca TURN (무료)

**주요 메서드**

| 메서드 | 설명 |
|---|---|
| `start({camera, mic})` | getUserMedia → RTCPeerConnection → offer 전송. 실패 시 `false` 반환 |
| `stop()` | 스트림 해제 + PC 닫기 |
| `handleAnswer(sdp)` | TD에서 온 answer 처리 |
| `handleIce({candidate, sdpMLineIndex, sdpMid})` | TD에서 온 ICE candidate 처리 |
| `onStateChange(fn)` | state 변화 콜백 등록. state: `connecting|connected|failed|closed` |
| `isMicActive()` | 마이크 스트림 활성 여부 |
| `isCameraActive()` | 카메라 스트림 활성 여부 |
| `getLastError()` | getUserMedia 실패 시 에러명 (e.g. `NotAllowedError`) |

**시그널링 흐름 (마이크 활성화)**

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
| `startBroadcast()` / `stopBroadcast()` | setInterval로 센서 데이터 주기 전송 |
| `sendTrigger()` | `{ type:'trigger' }` 단발 전송 |
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

## 6. TouchDesigner 파일 상세

### 6-1. `touchdesigner/callbacks.py` — Web Server DAT 콜백 (핵심)

TD의 Web Server DAT에 등록되는 메인 처리 파일.

**모듈 수준 함수 (TD가 직접 호출)**

| 함수 | 호출 시점 |
|---|---|
| `onHTTPRequest` | HTTP 요청 → `/cam_receiver.html` 로컬 서빙, 나머지는 GitHub Pages 리다이렉트 |
| `onWebSocketOpen` | WebSocket 연결 → 슬롯 할당 → ack + config 전송 |
| `onWebSocketClose` | 연결 끊김 → 슬롯 반납, sensor_table/webrtc_table 정리 |
| `onWebSocketReceiveText` | 텍스트 메시지 수신 → type별 처리 (cam_receiver와 모바일 분기) |

**수신 메시지 타입 처리 (모바일 → TD)**

| `type` | 처리 내용 |
|---|---|
| `sensor` | sensor_table 해당 슬롯 행 업데이트 + `data_ack` 응답 |
| `touch` | touch_table 업데이트 (기존 행 삭제 후 재삽입) + `data_ack` 응답 |
| `trigger` | `op('/').store(f'w2td_trig_{slot}', 1)` |
| `hello` | role 없음 → 로그 출력 / role=`cam_receiver` → cam_receiver 등록 (슬롯 반납) |
| `client_name` | 기기명 수신 → sensor_table `name` + webrtc_table `name` 업데이트 |
| `screen_info` | 화면 해상도 수신 → sensor_table (css/physical/screen/dpr) + `w2td_screen_{slot}` 저장 |
| `webrtc_offer` | `webrtc_dat.openConnection` + `setRemoteDescription` + `createAnswer` + webrtc_table 행 추가 |
| `webrtc_ice` | `webrtc_dat.addIceCandidate` |
| `webrtc_offer_cam` | 카메라 offer → cam_receiver로 relay (`cam_offer`) |
| `webrtc_ice_cam` | 카메라 ICE → cam_receiver로 relay (`cam_ice`) |
| `ping` | `pong` 응답 |

**cam_receiver → TD 메시지 처리**

| `type` | 처리 내용 |
|---|---|
| `cam_answer` | cam_receiver의 answer → 모바일에 relay (`webrtc_answer_cam`) |
| `cam_ice` | cam_receiver의 ICE → 모바일에 relay (`webrtc_ice_cam`) |
| `cam_resolution` | 수신된 video 해상도 로그 출력 (참고용) |

**Cross-DAT 상태 저장 패턴** (모듈 리로드 후 상태 유지)

```python
op('/').store('w2td_client_slots', dict)            # addr → slot 매핑
op('/').store('w2td_free_slots', list)              # 남은 슬롯
op('/').store('w2td_touch_count', dict)             # slot → touch count
op('/').store('w2td_client_names', dict)            # slot → 기기명
op('/').store('w2td_cam_receiver_addr', addr)       # cam_receiver WebSocket 주소
op('/').store(f'w2td_webrtc_addr_{conn_id}', addr)  # WebRTC conn_id → WS addr
op('/').store(f'w2td_webrtc_slot_to_uuid_{slot}', conn_id)  # slot → WebRTC UUID
op('/').store(f'w2td_screen_{slot}', dict)          # slot → 화면 해상도 정보
op('/').store(f'w2td_trig_{slot}', 1)               # trigger 펄스
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

### 6-2. `touchdesigner/w2td_init.py` — Execute DAT (onStart)

TD 프로젝트 시작 시 자동 실행.

**실행 흐름:**
```
onStart()
  → _init_tables()     # sensor_table, touch_table 초기화
  → _init_webrtc_ice() # WebRTC TURN 서버 설정
  → generate()
       → SSL 인증서 설정 (certifi)
       → tqdm 진행바 억제
       → pycloudflared.try_cloudflare(port=9980)   # cloudflared 터널 생성
       → op('/').store('w2td_url', url)              # URL 저장
       → QR URL 생성: GitHub Pages + ?td=터널호스트
       → W2TD base comp에 URL 설정 (par.url 또는 url_text Text DAT)
       → QR 코드 생성 → qr.png 저장
       → op('qr_movie_top').par.file = save_path    # Movie File In TOP 갱신
```

**주요 기능:**

1. **SSL 인증서 설정**
   - SSL 연결을 위한 `certifi` 인증서 번들 설정
   - 환경 변수 설정: `SSL_CERT_FILE`, `REQUESTS_CA_BUNDLE`
   - Python의 기본 SSL 컨텍스트를 certifi 사용하도록 설정
   - macOS SSL 인증서 검증 실패 문제 해결

2. **진행바 억제**
   - cloudflared 바이너리 다운로드 중 tqdm 진행바 억제
   - `contextlib.redirect_stdout`과 `redirect_stderr`로 다운로드 진행 상황 숨김
   - 로그를 깔끔하고 읽기 쉽게 유지

3. **Cloudflare 터널 생성**
   - 첫 실행: cloudflared 바이너리 (~17MB) 자동 다운로드
   - 이후 실행: 캐시된 바이너리 재사용
   - 터널 생성 실패 시 로컬 IP로 폴백

**필요 TD 노드:**

| 노드 이름 | 타입 | 용도 |
|---|---|---|
| `sensor_table` | Table DAT | 슬롯별 센서 데이터 |
| `touch_table` | Table DAT | 슬롯별 터치 포인트 |
| `w2td_config` | Table DAT | key\|value 설정값 (선택사항) |
| W2TD base comp | COMP | Custom Parameter `url` 또는 내부 Text DAT `url_text` — QR URL 표시 (선택사항) |
| `qr_movie_top` | Movie File In TOP | QR 코드 이미지 표시 (선택사항) |

---

### 6-3. `touchdesigner/w2td_setup.py` — 최초 1회 설치

TouchDesigner의 Python 환경에 필요한 패키지를 설치합니다.

**사용법:**
```python
# TD Textport 또는 Button DAT에서:
op('w2td_setup').module.install()
```

**설치되는 패키지:**

1. **certifi** (`--upgrade` 옵션으로)
   - SSL 인증서 번들
   - macOS SSL 인증서 검증 문제 해결
   - SSL이 제대로 작동하도록 먼저 설치

2. **qrcode[pil]**
   - QR 코드 생성 라이브러리
   - 이미지 처리를 위한 PIL (Pillow) 포함

3. **pycloudflared**
   - cloudflared 터널용 Python 래퍼
   - 참고: 첫 실행 시 cloudflared 바이너리 (~17MB) 자동 다운로드

**설치 순서:**
1. `certifi` (SSL 인증서)
2. `qrcode[pil]` (QR 코드 생성)
3. `pycloudflared` (Cloudflare 터널)

**중요 사항:**
- TouchDesigner의 Python (`sys.executable`) 사용, 시스템 Python 아님
- 플랫폼 인식: Windows는 `CREATE_NO_WINDOW` 플래그 사용
- 설치 후 TouchDesigner 재시작하여 SSL 인증서 로드 확인
- 설치 후 어느 디렉토리에서도 동작

---

### 6-4. `touchdesigner/webrtc_callbacks.py` — WebRTC DAT 콜백

`webrtc_dat` 노드의 Callbacks DAT에 연결.

**필요 TD 노드**

| 노드 이름 | 타입 | 설정 |
|---|---|---|
| `webrtc_dat` | WebRTC DAT | Callbacks DAT = `webrtc_callbacks` |
| `webrtc_audio_1` | Audio Stream In CHOP | Protocol=WebRTC, WebRTC DAT=`webrtc_dat`, Peer=1 |

> **참고**: Video Stream In TOP는 TD Pro 라이센스 전용. 마이크(Audio Stream In CHOP)는 일반 라이센스 사용 가능.

**콜백 함수**

| 함수 | 역할 |
|---|---|
| `onAnswer` | setLocalDescription + WebSocket으로 answer 전송 |
| `onIceCandidate` | ICE candidate를 WebSocket으로 모바일에 전달 |
| `onConnectionStateChange` | 상태 변화 → webrtc_table `state` 컬럼 업데이트. failed/closed 시 모바일에 알림. connected 시 `webrtc_audio_1` 자동 연결 |
| `onIceConnectionStateChange` | ICE 상태 변화 로그 |

**헬퍼 함수**

| 함수 | 역할 |
|---|---|
| `_wt_set_state(conn_id, state)` | webrtc_table에서 conn_id 행 찾아 state 컬럼 업데이트 |
| `_auto_select_audio_chop(webrtcDAT, connectionId)` | connected 시 `webrtc_audio_1` Connection 파라미터를 connectionId로 설정 |
| `_send_to_client(connectionId, data)` | `op('/').fetch('w2td_webserver_op')` + `op('/').fetch(f'w2td_webrtc_addr_{connectionId}')` → WebSocket 전송 |

---

## 7. Python 라이브러리

### 7-1. 필수 라이브러리

| 라이브러리 | 용도 | 설치 방법 |
|---------|------|----------|
| `certifi` | SSL 인증서 번들 (macOS SSL 문제 해결) | `w2td_setup.py`에서 자동 설치 |
| `qrcode[pil]` | QR 코드 생성 | `w2td_setup.py`에서 자동 설치 |
| `pycloudflared` | Cloudflare 터널 래퍼 | `w2td_setup.py`에서 자동 설치 |
| `numpy` | 위치 추정 (선택사항, `position_estimator.py`용) | 수동 설치 필요 |

### 7-2. 설치 방법

**권장: w2td_setup.py 사용**
```python
# TD Textport에서:
op('w2td_setup').module.install()
```

**수동 설치 (필요 시):**
```python
import subprocess
import sys
subprocess.check_call([sys.executable, '-m', 'pip', 'install', 'certifi', 'qrcode[pil]', 'pycloudflared', 'numpy'])
```

### 7-3. 중요 사항

- **TouchDesigner는 자체 Python 인터프리터 사용** — 시스템 Python과 별개
- 시스템 Python 설치 (`pip3 install ...`)는 TD에서 작동하지 않음
- 항상 `sys.executable` (TD의 Python) 사용하여 설치
- 각 기기에서 `w2td_setup.py`를 한 번 실행해야 함

### 7-4. pycloudflared 바이너리 다운로드

- `pycloudflared`는 Python 래퍼 라이브러리
- 첫 `try_cloudflare()` 호출 시 cloudflared 바이너리 (~17MB) 다운로드
- 바이너리는 OS/아키텍처별로 다름 (macOS Intel/ARM, Windows, Linux)
- 다운로드된 바이너리는 캐시되어 이후 실행에서 재사용
- 다운로드 진행바는 `w2td_init.py`에서 억제됨

---

## 8. WebSocket 메시지 전체 스펙

### 모바일 → TD

```json
{ "type": "hello" }
{ "type": "hello", "role": "cam_receiver" }
{ "type": "sensor", "ax": 0.1, "ay": -0.2, "az": 9.8, "ga": 1.2, "gb": -0.5, "gg": 0.3, "oa": 270.0, "ob": 5.0, "og": -2.0, "lat": 37.5, "lon": 127.0 }
{ "type": "touch", "count": 2, "t0x": 0.25, "t0y": 0.5, "t0s": 1, "t1x": 0.75, "t1y": 0.3, "t1s": 1 }
{ "type": "trigger" }
{ "type": "client_name", "name": "iPhone 15 Pro" }
{ "type": "screen_info", "width": 390, "height": 844, "physicalWidth": 1179, "physicalHeight": 2556, "screenWidth": 390, "screenHeight": 844, "devicePixelRatio": 3.0 }
{ "type": "webrtc_offer", "sdp": "..." }
{ "type": "webrtc_ice", "candidate": "...", "sdpMLineIndex": 0, "sdpMid": "0" }
{ "type": "webrtc_offer_cam", "sdp": "...", "camType": "rear" }
{ "type": "webrtc_ice_cam", "candidate": "...", "sdpMLineIndex": 0, "sdpMid": "0", "camType": "rear" }
{ "type": "ping" }
```

### TD → 모바일

```json
{ "type": "ack", "slot": 1 }
{ "type": "rejected", "reason": "Server is currently full..." }
{ "type": "config", "sample_rate": 30, "wake_lock": 1, "haptic": 1,
  "sensor_motion": 1, "sensor_orientation": 1, "sensor_geolocation": 0,
  "sensor_touch": 1, "dev_mode": 1,
  "sensor_rear_camera": 0, "sensor_front_camera": 0, "sensor_microphone": 1,
  "audio_echo_cancellation": 0, "audio_noise_suppression": 0, "audio_auto_gain": 0,
  "camera_resolution": "Non-Commercial", "camera_screenmode": "Portrait" }
{ "type": "webrtc_answer", "sdp": "..." }
{ "type": "webrtc_ice", "candidate": "...", "sdpMLineIndex": 0, "sdpMid": "0" }
{ "type": "webrtc_answer_cam", "sdp": "...", "camType": "rear" }
{ "type": "webrtc_ice_cam", "candidate": "...", "sdpMLineIndex": 0, "sdpMid": "0", "camType": "rear" }
{ "type": "webrtc_state", "state": "failed" }
{ "type": "data_ack" }
{ "type": "haptic", "pattern": [200, 100, 200] }
{ "type": "haptic", "state": 1 }
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
| `trig` | Trigger 펄스 (1발 후 자동 0) |
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

카메라 WebRTC는 마이크(TD WebRTC DAT)와 달리, TD 내부의 **Web Render TOP** + **cam_receiver.html**을 통해 처리됨.

```
모바일 → TD (callbacks.py) → cam_receiver.html (Web Render TOP, WebSocket ws://[local_ip]:9980)
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
  webrtc_offer_cam 수신 → cam_receiver addr로 cam_offer relay

cam_receiver.html (Web Render TOP):
  cam_offer 수신 → RTCPeerConnection 생성
  → setRemoteDescription(offer)
  → createAnswer
  → WS.send({ type:'cam_answer', slot, sdp, camType:'rear' })
  → ICE candidates 교환

TD callbacks.py:
  cam_answer → 모바일로 webrtc_answer_cam relay
  cam_ice    → 모바일로 webrtc_ice_cam relay

모바일:
  webrtc_answer_cam 수신 → setRemoteDescription
  ICE 교환 완료 → P2P 카메라 스트림 시작
```

**cam_receiver.html 서빙 방식**

- TD Web Server DAT가 `onHTTPRequest`에서 `/cam_receiver.html` 요청 감지
- `project.folder/cam_receiver.html` 파일을 읽어 직접 응답 (로컬 서빙)
- GitHub Pages 없이 TD 안에서 완결 → mixed-content 문제 없음
- `w2td_init.py`의 `generate()`에서 `web_render_top.par.url` = `http://local_ip:9980/cam_receiver.html?port=9980`

**cam_receiver.html 기능**

- WebSocket으로 `ws://[location.hostname]:9980` 연결 후 `hello { role:'cam_receiver' }` 전송
  → `location.hostname` = Web Render TOP가 로드한 실제 LAN IP (TLS cert mismatch 방지)
- TD가 cam_receiver 식별 후 슬롯 반납 (모바일 슬롯과 별도 관리)
- 후면/전면 카메라 각각 별도 RTCPeerConnection 관리 (`peerKey(slot, camType)`)
- 두 video 엘리먼트: `remote-video-rear`, `remote-video-front` (상호배타 — 동시 활성 불가)
- `ontrack` → `onloadedmetadata` 핸들러 등록 → `srcObject` 할당 → `play()` 명시 호출 (Web Render TOP Chromium autoplay 정책 대응)
- video 해상도 수신 시 `cam_resolution` 메시지로 TD에 전달 (참고용 로그)

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

1. `certifi` 설치 확인:
   ```python
   op('w2td_setup').module.install()
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

### 19-1. `touchdesigner/position_estimator.py` (선택사항)

이중 적분을 사용한 상대 위치 추정 (관성 항법).

**용도:**
- 시작점 기준 기기 위치 추정
- 가속도 + 기기 방향 데이터 사용
- `mobile_position` Constant CHOP에 출력 (x, y, z, 단위: 미터)

**요구사항:**
- `numpy` 라이브러리 (`w2td_setup.py`에 포함되지 않음, 별도 설치 필요)
- 3개 채널(x, y, z)을 가진 `mobile_position` Constant CHOP

**사용법:**
- `sensor_table` Table Change DAT에 연결
- 슬롯별로 추정기 자동 생성
- 위치 리셋: `op('/').fetch('w2td_relative_position_estimators', {}).get(1).reset_position()`

### 19-2. `touchdesigner/py/config_watch.py`

`w2td_config` Table DAT 변경 시 자동으로 config를 브로드캐스트합니다.

**설정:**
1. DAT Execute DAT 생성 (이름: `config_watch`)
2. "DATs" 파라미터를 `w2td_config`로 설정
3. "Table Change" 체크박스 활성화
4. `config_watch.py` 내용 붙여넣기 또는 연결

**참고:** 수동 `broadcast_config()` 호출 대안 — 변경 시 자동으로 config 푸시. Resolution, Screenmode 포함.
