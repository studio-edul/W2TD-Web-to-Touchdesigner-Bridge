# TouchDesigner 설정 가이드

> WOB 프로젝트를 TouchDesigner에서 사용하기 위한 설정 방법

---

## 📋 1. 필수 노드 목록

### 1-1. 생성해야 할 노드 전체

| 노드 이름 | 타입 | 필수 여부 |
|-----------|------|-----------|
| `web_server_dat` | **Web Server DAT** | 필수 |
| `sensor_table` | **Table DAT** | 필수 |
| `touch_table` | **Table DAT** | 필수 |
| `wob_config` | **Table DAT** | 필수 |
| `wob_init` | **Execute DAT** | 필수 |
| `config_watch` | **DAT Execute DAT** | 필수 |
| `qr_movie_top` | **Movie File In TOP** | 필수 (QR 표시) |
| `wob_url_text` | **Text DAT** | 필수 (QR URL 저장) |
| `wob_haptic` | **Constant CHOP** | 선택 (CHOP 진동 제어) |
| `haptic_exec` | **Execute CHOP** | 선택 (CHOP 진동 값 변경 감지) |
| `webrtc_dat` | **WebRTC DAT** | 선택 (카메라 스트리밍) |
| `web_render_top` | **Web Render TOP** | 선택 (카메라 수신) |

---

### 1-2. 노드별 상세 설정

#### `web_server_dat` — Web Server DAT

| 파라미터 | 값 |
|----------|----|
| Active | `On` ✅ |
| Port | `9980` |
| TLS | `On` ✅ |
| Callbacks DAT | `callbacks.py` 파일 연결 |

> **TLS On 이유**: 모바일 브라우저에서 WSS(보안 WebSocket) 연결을 위해 필요.
> 최초 접속 시 `https://[TD-IP]:9980` 로 접속해서 인증서 경고(고급 → 계속)를 수락하면 이후 자동 연결됩니다.

---

#### `wob_init` — Execute DAT (초기화)

| 파라미터 | 값 |
|----------|----|
| Script | `wob_init.py` 파일 연결 |
| Execute On | **On Start** ✅ |

역할:
- `sensor_table`, `touch_table` 헤더 초기화
- Cloudflare 터널 시작 및 QR 코드 생성
- `qr_movie_top`, `wob_url_text` 자동 업데이트

---

#### `config_watch` — DAT Execute DAT (설정 자동 갱신)

| 파라미터 | 값 |
|----------|----|
| DATs | `wob_config` |
| Table Change | ✅ 체크 |
| Script | `config_watch.py` 파일 연결 |

역할: `wob_config` 테이블 변경 시 300ms 디바운싱 후 모든 클라이언트에 자동 브로드캐스트.

---

#### `sensor_table` / `touch_table` — Table DAT

빈 Table DAT로 생성만 하면 됩니다. `wob_init` 실행 시 헤더가 자동으로 초기화됩니다.

**sensor_table 자동 설정 헤더:**
```
slot | connected | name | ax | ay | az | ga | gb | gg | oa | ob | og | lat | lon | touch_count | trig | css_width | css_height | physical_width | physical_height | screen_width | screen_height | device_pixel_ratio
```

---

### 1-3. `wob_config` Table DAT 내용

2열 구조 (헤더 행 없이 바로 데이터):

| key | value | 설명 |
|-----|-------|------|
| `port` | `9980` | Web Server 포트 |
| `max_clients` | `20` | 최대 동시 접속 수 |
| `sample_rate` | `30` | 센서 전송 주기 (Hz) |
| `wake_lock` | `1` | 화면 자동 꺼짐 방지 (0/1) |
| `haptic` | `1` | 진동 피드백 허용 (0/1) |
| `sensor_motion` | `1` | 가속도/자이로 센서 (0/1) |
| `sensor_orientation` | `1` | 방향 센서 (0/1) |
| `sensor_geolocation` | `0` | GPS (0/1) |
| `sensor_touch` | `1` | 터치 입력 (0/1) |
| `dev_mode` | `1` | 개발 모드 UI (0=자동 시작, 1=수동) |
| `sensor_camera` | `0` | 카메라 스트리밍 (0/1) |
| `sensor_microphone` | `1` | 마이크 (0/1) |
| `audio_echo_cancellation` | `0` | 에코 제거 (0/1) |
| `audio_noise_suppression` | `0` | 노이즈 억제 (0/1) |
| `audio_auto_gain` | `0` | 자동 게인 (0/1) |

> 선택 항목: `ice_servers` (TURN 서버 URL), `ice_transport_policy` (`relay` 고정 시)

---

### 1-4. Python 라이브러리 설치 (최초 1회)

**TouchDesigner Textport에서 실행:**
```python
op('wob_init').module.install_packages()
```

**설치되는 패키지:**
- `certifi` — SSL 인증서 (macOS 필수)
- `qrcode[pil]` — QR 코드 생성
- `pycloudflared` — Cloudflare 터널

> 설치 후 TouchDesigner를 재시작하세요.

---

## 🔗 2. 노드 연결 구조 요약

```
wob_config (Table DAT)
  └─ config_watch (DAT Execute DAT)
       └─ 변경 감지 시 web_server_dat.module.broadcast_config() 자동 호출

wob_init (Execute DAT) ──[On Start]──▶ sensor_table, touch_table 초기화
                                    └─▶ Cloudflare 터널 시작
                                    └─▶ qr_movie_top, wob_url_text 업데이트

web_server_dat (Web Server DAT)
  ├─ Callbacks: callbacks.py
  ├─ 읽기: sensor_table, touch_table, wob_config
  └─ (선택) webrtc_dat, web_render_top

wob_haptic (Constant CHOP) ──[Value Change]──▶ haptic_exec (Execute CHOP)
  └─ channels: slot1=0/1, slot2=0/1, ...       └─ 변경된 채널만 send_haptic_state() 호출
```

---

## 🎛️ 3. CHOP 기반 진동 제어 설정

### `wob_haptic` Constant CHOP

채널 이름 형식 (선택 가능):
- `slot1`, `slot2`, `slot3`, ... **(권장)**
- `ch1`, `ch2`, `ch3`, ...
- `1`, `2`, `3`, ...

값: `0` = 진동 중지, `1` = 지속 진동

### `haptic_exec` Execute CHOP (값 변경 감지)

| 파라미터 | 값 |
|----------|----|
| CHOPs | `wob_haptic` |
| Value Change | ✅ 체크 |
| Script | `haptic_chop_exec.py` 파일 연결 |

> Every Frame 폴링 방식보다 효율적 — 채널 값이 실제로 바뀔 때만 실행됩니다.

### 사용 예시

```
wob_haptic CHOP:
  slot1 = 1  →  Slot 1 모바일 진동 시작
  slot2 = 0  →  Slot 2 모바일 진동 중지
  slot3 = 1  →  Slot 3 모바일 진동 시작
```

### 다른 CHOP 이름 사용 시
```python
op('web_server_dat').module.broadcast_haptic_from_chop(op('web_server_dat'), 'my_haptic_chop')
```

---

## ⚙️ 4. 자동 갱신 설정 (Config Watcher)

`config_watch` DAT Execute DAT 설정 후 `wob_config` 테이블 값을 수정하면 자동으로 감지되어 300ms 디바운싱 후 모든 연결된 클라이언트에 브로드캐스트됩니다. 수동으로 `broadcast_config()` 호출이 불필요합니다.

**주의사항**: Web Server DAT 노드 이름이 `web_server_dat`가 아닌 경우 `config_watch.py` 내 `op("web_server_dat")` 부분을 수정하세요.

---

## 📝 5. 슬롯 이름 커스텀

### 모바일 측
1. 연결 모달에서 **"기기 이름"** 입력 필드에 이름 입력 (예: `iPhone_이지원`)
2. Connect 버튼 클릭 → 이름이 TD에 자동 전송

### TD 측
- `sensor_table`의 `name` 컬럼에서 슬롯별 이름 확인 가능
- 이름은 슬롯별로 저장되며 재연결 시에도 유지됨

### 자동 저장
- 입력한 이름은 localStorage에 저장되어 다음 접속 시 자동 입력

---

## 🔐 6. 통합 권한 요청 (dev_mode=0)

`wob_config`에서 `dev_mode` = `0` 설정 시:

모바일 "TAP TO START" 버튼 클릭 한 번으로:
1. 센서 권한 (DeviceMotionEvent) 요청
2. 마이크 권한 (getUserMedia) 요청
3. WakeLock 권한 (Screen Wake Lock API) 요청
4. 모든 권한 승인 후 자동으로 센서 수집 및 브로드캐스트 시작

> iOS에서는 user gesture 핸들러 내에서만 권한 요청 가능 — TAP TO START 버튼이 이 역할을 담당합니다.

---

## 🔄 7. WebSocket Heartbeat

모바일에서 자동으로 5초마다 ping을 전송하고, TD는 pong으로 응답합니다. pong이 10초 내에 오지 않으면 재연결을 시도합니다. 별도 설정 없이 자동 동작합니다.

**수동 호출 (선택사항):**
```python
# 모든 클라이언트에 heartbeat 전송
op('web_server_dat').module.send_heartbeat(op('web_server_dat'))

# 특정 슬롯에만 heartbeat 전송
op('web_server_dat').module.send_heartbeat(op('web_server_dat'), slot=1)
```

---

## 📊 8. 데이터 수신 확인 (Ack Signal)

TD가 센서/터치 데이터를 수신하면 자동으로 `data_ack` 메시지를 전송합니다. 모바일 하단 바의 **녹색 점이 깜빡이면** 데이터가 TD에 정상 도달 중입니다. 별도 설정 없이 자동 동작합니다.

---

## 🛠️ 9. 주요 함수 참조 (Textport 또는 스크립트에서 호출)

### 진동 제어

```python
# 패턴 기반 — 특정 슬롯
op('web_server_dat').module.send_haptic_to_client(op('web_server_dat'), slot=1, pattern=[200, 100, 200])

# 패턴 기반 — 전체 클라이언트
op('web_server_dat').module.send_haptic_to_all(op('web_server_dat'), pattern=[200])

# 상태 기반 — 진동 시작
op('web_server_dat').module.send_haptic_state(op('web_server_dat'), slot=1, state=1)

# 상태 기반 — 진동 중지
op('web_server_dat').module.send_haptic_state(op('web_server_dat'), slot=1, state=0)

# CHOP 기반 (haptic_exec에서 자동 호출)
op('web_server_dat').module.broadcast_haptic_from_chop(op('web_server_dat'))
```

### 설정 브로드캐스트

```python
# 수동으로 설정 전송 (config_watch 사용 시 자동)
op('web_server_dat').module.broadcast_config(op('web_server_dat'))
```

---

## ⚙️ 10. 포트 설정 (같은 PC에서 여러 프로젝트 실행 시)

1. `wob_config` Table DAT에 `port` 키 추가
2. Web Server DAT의 Port 파라미터도 동일한 값으로 변경
3. TD 프로젝트 재시작

```
프로젝트 1: wob_config port=9980 ↔ web_server_dat Port=9980
프로젝트 2: wob_config port=9981 ↔ web_server_dat Port=9981
프로젝트 3: wob_config port=9982 ↔ web_server_dat Port=9982
```

> 다른 PC끼리는 IP가 다르므로 같은 포트를 사용해도 충돌하지 않습니다.

---

## ❗ 11. 문제 해결

### CHOP 진동이 작동하지 않는 경우
1. CHOP 노드 이름이 `wob_haptic`인지 확인
2. 채널 이름 확인 (`slot1`, `slot2`, ...)
3. `haptic_exec` Execute CHOP의 **CHOPs** 파라미터에 `wob_haptic`이 설정되어 있는지 확인
4. `haptic_exec` Execute CHOP의 **Value Change**가 체크되어 있는지 확인
5. Web Server DAT 이름이 `web_server_dat`인지 확인

### 자동 갱신이 작동하지 않는 경우
1. `config_watch` DAT Execute DAT의 **Table Change** 체크박스 활성화 여부 확인
2. **DATs** 파라미터에 `wob_config`가 설정되어 있는지 확인
3. Web Server DAT 이름이 `web_server_dat`인지 확인

### 슬롯 이름이 표시되지 않는 경우
1. 모바일에서 이름 입력 후 Connect 했는지 확인
2. `sensor_table`에 `name` 컬럼이 있는지 확인
3. TD 프로젝트 재시작으로 테이블 구조 업데이트

### Cloudflare 터널이 실패하는 경우
1. 패키지 설치: `op('wob_init').module.install_packages()`
2. 설치 후 TD 재시작
3. Textport에서 `[WOB] SSL certificates configured` 메시지 확인
4. 실패 시 로컬 IP로 자동 폴백됨 (같은 네트워크에서만 접속 가능)

---

## 📚 12. 참고 자료

- 상세 개발 문서: `development/DEV_DOCS.md`
- 개발 로드맵: `development/ROADMAP.md`
- 프로젝트 README: `README.md`

---

**마지막 업데이트**: 2026-02-28
