# WOB — Web-to-TouchDesigner Bridge

모바일 브라우저의 센서 데이터(모션, 오리엔테이션, 터치, GPS)를 WebSocket으로 TouchDesigner에 실시간 전송하는 시스템.

```
[모바일 브라우저] ──WebSocket (WSS)──> [ngrok 터널] ──> [TouchDesigner Web Server DAT]
  GitHub Pages (HTTPS)                                    포트 9980 (TLS OFF)
```

모바일에서 인증서 설정이나 별도 서버 없이 바로 연결됩니다.

---

## 빠른 시작

### 1. TouchDesigner 설정

#### 필요한 DAT 노드

| 노드 | 타입 | 이름 | 역할 |
|------|------|------|------|
| Web Server DAT | DAT → Web Server | 임의 | WebSocket 연결 수신 |
| Callbacks Script | DAT → Text | `callbacks` (Web Server DAT에서 지정) | `callbacks.py` 내용 |
| Execute DAT | DAT → Execute | `wob_init` | `wob_init.py` 내용 — TD 시작 시 자동 실행 |
| Table DAT | DAT → Table | `sensor_table` | `init_tables()` 가 자동 생성 |
| Table DAT | DAT → Table | `touch_table` | `init_tables()` 가 자동 생성 |

**Web Server DAT 파라미터:**
- Active: `On`
- Port: `9980`
- TLS: `Off` (ngrok 사용 시 필수)

#### 선택 설정 DAT

`wob_config` 라는 이름의 **Table DAT**를 만들면 코드 수정 없이 설정을 바꿀 수 있습니다:

| key | value |
|-----|-------|
| max_clients | 20 |

#### wob_init.py (Execute DAT)

`touchdesigner/wob_init.py` 내용을 Execute DAT에 붙여넣습니다.
- TD 시작 시 `onStart()` 자동 실행
- `init_tables()` 호출 → sensor_table / touch_table 초기화
- ngrok 터널 시작 + QR 코드 생성

필요한 Python 패키지 (최초 1회 설치):
```
pip install qrcode pillow pyngrok
ngrok config add-authtoken <YOUR_TOKEN>
```

#### callbacks.py (Web Server DAT Callbacks)

`touchdesigner/callbacks.py` 내용을 Web Server DAT의 Callbacks Script DAT에 붙여넣습니다.

### 2. 모바일 연결

1. TD 실행 → `wob_init.py`가 ngrok을 시작하고 QR 코드 생성 (`qr_movie_top` TOP에 표시)
2. QR 코드 스캔 → `?td=` 파라미터가 미리 채워진 GitHub Pages로 바로 이동
3. **Enable Sensors** 탭 → 센서 자동 활성화
4. TD로 데이터 전송 시작

### 3. TD에서 데이터 읽기

**sensor_table DAT** — 연결된 기기마다 한 행 (슬롯 1~20):

| 컬럼 | 설명 | 범위 |
|------|------|------|
| `slot` | 기기 슬롯 번호 | 1 ~ 20 |
| `connected` | 연결 상태 | 0 또는 1 |
| `ax` `ay` `az` | 가속도 (중력 포함) | m/s² (약 ±15) |
| `ga` `gb` `gg` | 자이로 회전속도 | deg/s |
| `oa` | 오리엔테이션 alpha (나침반/Yaw) | 0 ~ 360° |
| `ob` | 오리엔테이션 beta (앞뒤 기울기/Pitch) | -180 ~ 180° |
| `og` | 오리엔테이션 gamma (좌우 기울기/Roll) | -90 ~ 90° |
| `lat` `lon` | GPS 좌표 | 도(degree) |
| `touch_count` | 현재 터치 개수 | 정수 |
| `trig` | 트리거 버튼 펄스 (한 패킷 동안 1) | 0 또는 1 |

**touch_table DAT** — 활성 터치 포인트마다 한 행:

| 컬럼 | 설명 |
|------|------|
| `slot` | 기기 슬롯 |
| `touch_id` | 터치 인덱스 (0부터) |
| `x` `y` | 터치 위치 (정규화 0~1) |
| `state` | 1 = 터치 중 |

**CHOP으로 읽는 방법:**
- `sensor_table` → **DAT to CHOP** 연결
- `First Row is Names: On`, `Select Rows: By Index` → 행 `1` (슬롯 1번 기기)
- 범위 조정이 필요하면 **Math CHOP** 사용 (예: `oa` 0~360 → 0~1)

---

## 동작 구조

- TD Web Server DAT가 포트 `9980`에서 대기 (TLS 없음)
- `wob_init.py`가 ngrok HTTP 터널 시작 → 공개 주소 `wss://xxxx.ngrok-free.app` 생성
- QR 코드는 `https://studio-edul.github.io/Web-Osc-Bridge/?td=xxxx.ngrok-free.app` 인코딩
- 모바일이 GitHub Pages에 직접 접속 → ngrok 인터스티셜 페이지 없음
- WebSocket은 ngrok 터널(`wss://`) 경유 — GitHub Pages(HTTPS)에서는 WSS 필수

### callbacks.py 리로드 후 상태 유지

클라이언트 슬롯 정보는 `op('/').store/fetch`로 저장되어, TD 내에서 스크립트가 리로드되어도 연결이 끊기지 않습니다.

### 다중 기기 지원

최대 `max_clients`대 (기본 20대) 동시 접속 가능. 연결 시 슬롯 자동 배정, 종료 시 반환.

---

## 데이터 포맷 (WebSocket JSON)

### 센서 패킷 (설정된 Hz로 전송)
```json
{
  "type": "sensor",
  "ax": -0.12, "ay": 0.34, "az": 9.76,
  "ga": 12.5,  "gb": -3.2, "gg": 0.8,
  "oa": 183.4, "ob": -12.0, "og": 5.3,
  "lat": 37.5665, "lon": 126.9780
}
```

### 터치 패킷
```json
{
  "type": "touch",
  "count": 2,
  "t0x": 0.35, "t0y": 0.72, "t0s": 1,
  "t1x": 0.68, "t1y": 0.45, "t1s": 1
}
```

### 트리거 패킷 (버튼 누름)
```json
{ "type": "trigger" }
```
TD에서 `sensor_table[slot, 'trig'] = 1`로 설정되고, 다음 센서 패킷에서 자동으로 0으로 리셋됩니다.

---

## 주요 기능

- 모션 센서 (가속도계 + 자이로) — 원본 m/s², deg/s 값
- 오리엔테이션 (Yaw/Pitch/Roll) — 원본 도(degree) 값
- 멀티터치 트래킹 (위치 0~1 정규화)
- GPS (위도/경도)
- 트리거 버튼 (TD로 1회 펄스 전송)
- 최대 20대 동시 연결
- 실시간 Canvas 시각화 (선택된 센서만 표시)
- 샘플레이트 조절 (5~60 Hz)
- Wake Lock (화면 꺼짐 방지)
- 자동 재연결 (지수 백오프)
- 설정 LocalStorage 저장
- 로그 패널 숨기기/보이기

---

## 프로젝트 구조

```
docs/               ← GitHub Pages (웹 앱)
  index.html
  js/
    app.js          ← 앱 메인 로직, 브로드캐스트 루프
    sensors.js      ← 센서 감지, 권한, 원본 데이터 수집
    websocket.js    ← WebSocket 클라이언트, 재연결
    visualization.js← Canvas 스파크라인 렌더러
    ui.js           ← UI 유틸리티

touchdesigner/
  callbacks.py      ← Web Server DAT 콜백 (WebSocket 처리, sensor_table 쓰기)
  wob_init.py       ← Execute DAT (ngrok 시작, QR 생성, 테이블 초기화)
```

> **워크플로우:** `docs/` 파일만 GitHub에 push합니다. Python 파일은 TD에서 직접 적용 (파일 수정 시 DAT 자동 업데이트).

---

## 참고 자료

- [Web Server DAT — TouchDesigner Docs](https://docs.derivative.ca/Web_Server_DAT)
- [Device Orientation API — MDN](https://developer.mozilla.org/en-US/docs/Web/API/DeviceOrientationEvent)
- [Device Motion API — MDN](https://developer.mozilla.org/en-US/docs/Web/API/DeviceMotionEvent)
