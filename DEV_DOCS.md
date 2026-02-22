# WOB (Web-OSC-Bridge) 개발 문서

> 최종 업데이트: 2026-02-22
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

## 2. 파일 구조 전체 맵

```
Web-Osc-Bridge/
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
│   ├── callbacks.py               ← TD Web Server DAT 콜백 (메인)
│   ├── wob_init.py                ← TD Execute DAT onStart: cloudflared + QR
│   ├── wob_setup.py               ← 최초 1회 pip 패키지 설치
│   └── webrtc_callbacks.py        ← TD WebRTC DAT 콜백 (마이크 시그널링)
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

## 3. 아키텍처 상세

### 3-1. 연결 흐름

```
모바일 QR 스캔
  → GitHub Pages /?td=xxxx.trycloudflare.com
  → WebSocket 연결 (wss://xxxx.trycloudflare.com)
  → TD onWebSocketOpen → slot 할당 → ack + config 전송
  → 모바일: config 수신 → 센서/마이크 자동활성화
  → 모바일: sensor 메시지 브로드캐스트 → TD sensor_table 업데이트
```

### 3-2. 슬롯 시스템

- 클라이언트마다 슬롯 번호(1~MAX_CLIENTS) 할당
- `op('/').store('wob_client_slots', dict)` — addr → slot 매핑
- `op('/').store('wob_free_slots', list)` — 남은 슬롯 목록
- 연결 끊기면 슬롯 반납, `sensor_table` 행 삭제

### 3-3. Config 시스템 (TD → 모바일)

TD의 `wob_config` Table DAT에서 값을 읽어 연결 시 모바일로 push.

| wob_config 키 | 기본값 | 설명 |
|---|---|---|
| `sample_rate` | 30 | 브로드캐스트 Hz |
| `wake_lock` | 1 | 화면 잠금 방지 |
| `haptic` | 1 | 진동 피드백 |
| `sensor_motion` | 1 | 가속도+자이로 활성화 |
| `sensor_orientation` | 1 | 방향각 활성화 |
| `sensor_geolocation` | 0 | GPS 활성화 |
| `sensor_touch` | 1 | 터치 활성화 |
| `dev_mode` | 1 | 1=풀 UI, 0=터치패드만 |
| `sensor_camera` | 0 | 카메라 (Pro 전용, 미구현) |
| `sensor_microphone` | 0 | 마이크 WebRTC 자동활성화 |
| `max_clients` | 20 | 최대 접속 수 |

---

## 4. 웹 파일 상세

### 4-1. `docs/index.html`

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
| `wob-loading` | QR 접속 후 config 대기 로딩 화면 |
| `webrtc-preview` | 카메라 미리보기 video (현재 미사용) |

---

### 4-2. `docs/css/style.css`

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

### 4-3. `docs/js/websocket.js` — `WSClient`

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

### 4-4. `docs/js/sensors.js` — `SensorModule`

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

### 4-5. `docs/js/touch.js` — `TouchModule`

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

### 4-6. `docs/js/visualization.js` — `Visualization`

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

### 4-7. `docs/js/webrtc.js` — `WebRTCModule`

WebRTC 피어 연결 관리. 시그널링은 기존 WebSocket 재활용.

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

### 4-8. `docs/js/app.js` — 메인 컨트롤러

모든 모듈을 조율하는 IIFE.

**주요 상태 변수**

| 변수 | 의미 |
|---|---|
| `broadcasting` | 센서 브로드캐스트 중 여부 |
| `sampleRate` | 브로드캐스트 Hz (config로 변경) |
| `devMode` | true=풀UI / false=터치패드만 |
| `touchPadActive` | 터치패드 표시 중 여부 |
| `cameraEnabled` | config `sensor_camera` 값 |
| `micEnabled` | config/클릭으로 설정된 마이크 활성 의도 |

**주요 함수**

| 함수 | 역할 |
|---|---|
| `init()` | DOM 캐시 → 설정 로드 → 이벤트 바인딩 → URL ?td= 자동연결 |
| `applyConfig(cfg)` | TD config 메시지 처리 (sample_rate, 센서 선택, dev_mode, 마이크 등) |
| `applyDevMode(on)` | dev_mode=0: 메인 UI 숨기고 터치패드 직접 표시 |
| `renderSensorList()` | 센서 목록 재렌더. Motion/Orient/Geo/Touch/Camera/Mic 항목 포함 |
| `handleConnect()` | WebSocket 연결 시작 → 로딩화면 또는 UI 표시 |
| `handleMicToggle()` | 마이크 토글. 클릭 즉시 `micEnabled=true` → UI 업데이트 → WebRTC 시작 |
| `handleEnableSensors()` | 센서 권한 요청 + 수집 시작/중지 |
| `enterTouchPad()` / `exitTouchPad()` | 터치패드 전환 |
| `startBroadcast()` / `stopBroadcast()` | setInterval로 센서 데이터 주기 전송 |
| `sendTrigger()` | `{ type:'trigger' }` 단발 전송 |
| `_showTouchPadDirectly()` | dev_mode=0 진입 시 — iOS 첫 탭으로 센서 권한 요청 처리 |
| `_startWebRTC()` | config 자동활성화용. WSClient 연결 확인 후 WebRTC 시작 |

**센서 목록 렌더링 패턴**

`renderSensorList()`는 다음 이벤트 발생 시 항상 호출됨:
- 센서 항목 탭
- WebRTC 상태 변화 (`onStateChange`)
- `handleMicToggle` 시작·종료 시
- `applyConfig` 에서 sensor_microphone 변경 시

---

## 5. TouchDesigner 파일 상세

### 5-1. `touchdesigner/callbacks.py` — Web Server DAT 콜백 (핵심)

TD의 Web Server DAT에 등록되는 메인 처리 파일.

**모듈 수준 함수 (TD가 직접 호출)**

| 함수 | 호출 시점 |
|---|---|
| `onHTTPRequest` | HTTP GET 요청 → GitHub Pages로 리다이렉트 |
| `onWebSocketOpen` | WebSocket 연결 → 슬롯 할당 → ack + config 전송 |
| `onWebSocketClose` | 연결 끊김 → 슬롯 반납, sensor_table 행 삭제 |
| `onWebSocketReceiveText` | 텍스트 메시지 수신 → type별 처리 |

**수신 메시지 타입 처리**

| `type` | 처리 내용 |
|---|---|
| `sensor` | sensor_table 해당 슬롯 행 업데이트 |
| `touch` | touch_table 업데이트 (기존 행 삭제 후 재삽입) |
| `trigger` | `op('/').store(f'wob_trig_{slot}', 1)` |
| `hello` | 로그 출력 |
| `webrtc_offer` | `webrtc_dat.setRemoteDescription` + `createAnswer` |
| `webrtc_ice` | `webrtc_dat.addIceCandidate` |

**Cross-DAT 상태 저장 패턴** (모듈 리로드 후 상태 유지)

```python
op('/').store('wob_client_slots', dict)   # addr → slot 매핑
op('/').store('wob_free_slots', list)     # 남은 슬롯
op('/').store('wob_touch_count', dict)    # slot → touch count
op('/').store('wob_webserver_op', path)   # webrtc_callbacks에서 사용
op('/').store(f'wob_webrtc_addr_{slot}', addr)  # WebRTC per-slot
op('/').store(f'wob_trig_{slot}', 1)      # trigger 펄스
```

**유용한 함수**

```python
# config 전체를 모든 클라이언트에 다시 push (wob_config 수정 후 TD 스크립트에서 호출)
op('web_server_dat').module.broadcast_config(op('web_server_dat'))
```

---

### 5-2. `touchdesigner/wob_init.py` — Execute DAT (onStart)

TD 프로젝트 시작 시 자동 실행.

```
onStart()
  → _init_tables()     # sensor_table, touch_table 초기화
  → generate()
       → pycloudflared.try_cloudflare(port=9980)   # cloudflared 터널 생성
       → op('/').store('wob_url', url)              # URL 저장
       → QR URL 생성: GitHub Pages + ?td=터널호스트
       → op('wob_url_text').par.text = qr_url       # 텍스트 노드에 URL 표시
       → qrcode 생성 → qr.png 저장
       → op('qr_movie_top').par.file = save_path    # Movie File In TOP 갱신
```

**TD 필요 노드**

| 노드 이름 | 타입 | 용도 |
|---|---|---|
| `sensor_table` | Table DAT | 슬롯별 센서 데이터 |
| `touch_table` | Table DAT | 슬롯별 터치 포인트 |
| `wob_config` | Table DAT | key\|value 설정값 |
| `wob_url_text` | Text DAT / Text TOP | QR URL 표시 |
| `qr_movie_top` | Movie File In TOP | QR 이미지 표시 |

---

### 5-3. `touchdesigner/wob_setup.py` — 최초 1회 설치

```python
# TD Textport 또는 Button DAT에서 실행
op('wob_setup').module.install()
# → qrcode[pil] 및 pycloudflared를 TD의 전역 Python에 설치
```

설치 후 어느 디렉토리에서 .toe 파일을 열어도 동작.

---

### 5-4. `touchdesigner/webrtc_callbacks.py` — WebRTC DAT 콜백

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
| `onConnectionStateChange` | failed/closed 시 모바일에 알림 |

`_send_to_client(connectionId, data)` 내부:
- `op('/').fetch('wob_webserver_op')` → Web Server DAT 참조
- `op('/').fetch(f'wob_webrtc_addr_{connectionId}')` → 클라이언트 주소

---

## 6. WebSocket 메시지 전체 스펙

### 모바일 → TD

```json
{ "type": "hello" }
{ "type": "sensor", "ax": 0.1, "ay": -0.2, "az": 9.8, "ga": 1.2, "gb": -0.5, "gg": 0.3, "oa": 270.0, "ob": 5.0, "og": -2.0, "lat": 37.5, "lon": 127.0 }
{ "type": "touch", "count": 2, "t0x": 0.25, "t0y": 0.5, "t0s": 1, "t1x": 0.75, "t1y": 0.3, "t1s": 1 }
{ "type": "trigger" }
{ "type": "webrtc_offer", "sdp": "..." }
{ "type": "webrtc_ice", "candidate": "...", "sdpMLineIndex": 0, "sdpMid": "0" }
```

### TD → 모바일

```json
{ "type": "ack", "slot": 1 }
{ "type": "rejected", "reason": "Server is currently full..." }
{ "type": "config", "sample_rate": 30, "wake_lock": 1, "haptic": 1,
  "sensor_motion": 1, "sensor_orientation": 1, "sensor_geolocation": 0,
  "sensor_touch": 1, "dev_mode": 1, "sensor_camera": 0, "sensor_microphone": 0 }
{ "type": "webrtc_answer", "sdp": "..." }
{ "type": "webrtc_ice", "candidate": "...", "sdpMLineIndex": 0, "sdpMid": "0" }
{ "type": "webrtc_state", "state": "failed" }
```

---

## 7. TD sensor_table 구조

| 컬럼 | 설명 |
|---|---|
| `slot` | 클라이언트 슬롯 번호 |
| `connected` | 1=연결 중 |
| `ax` `ay` `az` | 가속도 m/s² |
| `ga` `gb` `gg` | 자이로 deg/s |
| `oa` `ob` `og` | 방향각 deg |
| `lat` `lon` | GPS 좌표 |
| `touch_count` | 현재 터치 수 |
| `trig` | Trigger 펄스 (1발 후 자동 0) |

Row 0 = 헤더, Row 1~ = 슬롯 데이터 (동적 추가/삭제)

---

## 8. dev_mode 동작

| dev_mode | UI 형태 | 센서 활성화 방식 |
|---|---|---|
| `1` (개발/전시자용) | 풀 UI (센서목록, 그래프, 브로드캐스트 바) | Enable Sensors 버튼 탭 |
| `0` (사용자/전시용) | 풀스크린 터치패드만 | 첫 터치 시 자동 (iOS는 TAP TO START 버튼) |

`localStorage('wob-dev-mode')` 에 캐시 → 다음 접속 시 플래시 없이 즉시 적용.

---

## 9. iOS 권한 처리 특이사항

- `DeviceMotionEvent.requestPermission()` — **직접적인 user gesture** 에서만 가능
- `getUserMedia()` — user gesture 직후 async 체인에서 호출 가능 (iOS 15+)
- dev_mode=1: Enable Sensors 버튼 탭 → `requestPermissions()` 호출
- dev_mode=0: TAP TO START 버튼 탭 → `requestPermissions()` 호출
- 마이크: Microphone 항목 탭 → `getUserMedia()` 호출

---

## 10. 주요 수정 가이드

### config 키 추가하기

1. `callbacks.py` `_config_msg()` 에 키 추가
2. `app.js` `applyConfig()` 에 처리 로직 추가
3. `wob_config` Table DAT에 행 추가 (TD에서)

### 새 메시지 타입 추가하기

1. 모바일 → TD: `websocket.js`의 `send()` 또는 새 sendXxx() 함수, `callbacks.py` `onWebSocketReceiveText` 에 elif 추가
2. TD → 모바일: `callbacks.py`에서 `webSocketSendText()`, `websocket.js` `onmessage` 에 라우팅 추가, `app.js`에 처리 로직 추가

### 센서 목록에 새 항목 추가하기

`app.js` `renderSensorList()` 내부에서 `els.sensorList.appendChild(li)` 패턴 따라 추가. CSS 클래스: `available selected/deselected` 또는 `unavailable`.

---

## 11. 알려진 제한사항

| 항목 | 내용 |
|---|---|
| Video Stream In TOP | TD Pro 라이센스 전용 → Camera 항목은 UI에 표시되지만 비활성 |
| cloudflared URL | TD 재시작마다 URL 변경 → QR 재스캔 필요 |
| 마이크 권한 거부 시 | 팝업 없이 조용히 실패 → 브라우저 설정에서 수동 허용 필요 |
| GitHub Pages HTTPS | ws:// 불가, 반드시 wss:// (cloudflared 필수) |
| 로컬 IP 직접 접속 | GitHub Pages에서 mixed content 차단 → cloudflared 필수 |

---

## 12. 마이크 문제 해결 가이드

### 증상: 권한 팝업이 뜨지 않고 마이크가 활성화되지 않음

**원인**: 브라우저가 해당 도메인의 마이크 권한을 이미 "거부"로 기억하고 있어 조용히 실패.

**해결 방법 (사용자)**

| 브라우저 | 방법 |
|---|---|
| iOS Safari | 설정 → Safari → 마이크 → studio-edul.github.io → 허용 |
| Android Chrome | 주소창 자물쇠 아이콘 → 권한 → 마이크 → 허용 |
| 데스크톱 Chrome | 주소창 자물쇠 → 이 사이트 권한 → 마이크 → 허용 |

**코드 측 동작**: 권한 거부 시 `NotAllowedError` 포착 → 로그 패널에 한국어 안내 메시지 표시.

### 증상: config `sensor_microphone=1`로 설정했는데 실제 연결이 안 됨

- config auto-start (`_startWebRTC`)는 WebSocket 메시지 핸들러에서 호출 → **iOS에서 user gesture 없이 getUserMedia 불가** → 조용히 실패
- UI는 초록(micEnabled=true)으로 표시되지만 실제 스트림 없음
- 사용자가 Microphone 항목을 직접 탭해서 활성화해야 함

### toggle 로직 설계 원칙

`handleMicToggle`의 toggle 방향은 **`micEnabled`** (사용자 의도) 기준으로 결정.
`WebRTCModule.isMicActive()` (실제 스트림 상태)를 기준으로 하면 config auto-start 실패 상태에서 방향이 반전되는 버그 발생.

```
micEnabled=true  → 탭 → DISABLE 경로 (stop + micEnabled=false)
micEnabled=false → 탭 → ENABLE 경로  (start + getUserMedia)
```

---

## 13. 이 문서 업데이트 방법

새 기능 추가·버그 수정 후 이 파일에 반영:

1. **새 기능 추가 시**: 해당 파일 섹션(4.x ~ 5.x)에 함수·메서드 설명 추가, 필요 시 섹션 신설
2. **config 키 변경/추가 시**: 섹션 3(Config 시스템 표) + 섹션 6(메시지 스펙) 업데이트
3. **새 WebSocket 메시지 타입**: 섹션 6(메시지 스펙) 업데이트
4. **TD 노드 변경 시**: 섹션 5(TouchDesigner 파일) + 관련 노드 표 업데이트
5. **알려진 버그/제한사항**: 섹션 11~12 업데이트

> 다른 채팅 세션에서 개발 시작 시 이 문서를 먼저 읽고, 작업 완료 후 관련 섹션을 업데이트할 것.
