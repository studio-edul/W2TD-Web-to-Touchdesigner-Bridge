# Stay-tion 2026 Korail — 실시간 속도 선 그래프

> **RULE**: 이 폴더의 코드 파일을 수정할 때는 반드시 이 README도 함께 업데이트한다.

---

## 개요

모바일 기기의 가속도계 데이터를 W2TD를 통해 받아,
각 참가자의 **실시간 속도**를 캔버스에 선으로 표현하는 시스템.

- **정지(speed ≈ 0)** → 선의 기울기 = 0 → 수평선
- **이동(speed > 0)** → 속도에 비례해 선이 위로 올라감
- **절대 시간 축**: 모바일이 멈춰도 X축은 계속 진행
- **Feedback 미사용**: Python 버퍼가 전체 히스토리를 보존, GLSL이 매 프레임 전체를 다시 그림
- 여러 참가자가 각기 다른 색으로 동시에 그려짐

---

## 파일 구조

```
2026_korail/code/
├── line_chop.py     Script CHOP — position_table 읽기 + 상태 계산 + 채널 출력
├── line_glsl.frag   GLSL TOP 쉐이더 — 선분 SDF 렌더
└── README.md        이 파일
```

**의존 파일 (이 폴더 바깥):**
```
touchdesigner-examples/
└── position_estimator_v2.py   sensor_table → position_table (속도 계산)
```

---

## 데이터 흐름

```
sensor_table (W2TD 기본)
    │
    ▼
[DAT Execute: position_estimator_v2.py]
    │  position_table 생성
    │  컬럼: slot | x | y | z | vx | vy | vz | speed | stationary
    ▼
[Script CHOP: line_chop.py]   ← 매 프레임 cook() 실행
    │  · position_table 직접 읽기
    │  · 채널별 y값 누적 (절대 시간 인덱스 기반)
    │  · 채널 수 = 누적 접속 횟수 (재접속 시 채널 추가)
    │  · 각 채널: HISTORY_LEN 샘플, 시작 전 구간 = NO_DATA(-1000)
    ▼
[CHOP to TOP]
    │  width = HISTORY_LEN, height = 채널 수
    ▼
[GLSL TOP: line_glsl.frag]   ← Input 0: CHOP to TOP
    │  texelFetch로 각 슬롯의 y값 읽기
    │  NO_DATA(-1000) 구간 스킵
    │  선분 SDF로 렌더
    ▼
   출력
```

---

## TD 노드 세팅

### 1. position_estimator 세팅 (이미 있다면 스킵)

| 항목 | 값 |
|------|----|
| 노드 종류 | DAT Execute DAT |
| DATs | `sensor_table` 경로 |
| Table Change | ✅ ON |
| 내용 | `position_estimator_v2.py` 붙여넣기 |

→ `position_table` DAT이 자동 생성됨

---

### 2. line_chop (Script CHOP)

| 항목 | 값 |
|------|----|
| 노드 종류 | Script CHOP |
| Script 탭 > DAT | 새 Text DAT 생성 후 `line_chop.py` 내용 붙여넣기 |
| Always Cook | ✅ ON |

---

### 3. chop_to_top (CHOP to TOP)

| 항목 | 값 |
|------|----|
| 노드 종류 | CHOP to TOP |
| CHOP | `line_chop` 경로 |
| Pixel Format | 32-bit float (Mono) |

---

### 4. line_glsl_top (GLSL TOP)

| 항목 | 값 |
|------|----|
| 노드 종류 | GLSL TOP |
| **Input 0 (와이어)** | `chop_to_top` 연결 |
| GLSL 탭 > Pixel Shader | `glsl_pixel` DAT에 `line_glsl.frag` 내용 붙여넣기 |
| Pixel Format | 32-bit float |
| Resolution | 원하는 출력 해상도 (예: 1920×1080) |

**Vectors 탭 — Uniform 추가:**

| Uniform Name | Type | Value |
|--------------|------|-------|
| `uLineWidth` | float | `0.002` |

---

### 5. 컨테이너 Custom Parameters

`stay_diagram` COMP (line_chop을 담은 컨테이너) 우클릭 → Edit Custom Parameters:

| 이름 | 타입 | 기본값 | 범위 | 설명 |
|------|------|--------|------|------|
| `Speedscale` | Float | `2.0` | 0 – 20 | **전체 기울기 배율** (핵심 슬라이더) |
| `Sessionduration` | Float | `28800` | 60 – 86400 | 세션 총 시간(초) — X축 전체 범위 |

---

## 핵심 동작 원리

### 절대 시간 축

- `HISTORY_LEN = 2000` 샘플이 `Sessionduration` 초를 균등 분할
- 현재 시간 → `t_to_idx()` → 버퍼 인덱스
- 매 프레임 `cook()`에서 인덱스가 증가 → 선이 오른쪽으로 진행
- 모바일 정지 시: `speed=0` → `cur_y` 증가 없음 → 수평 구간 기록

### 채널 관리

| 이벤트 | 동작 |
|--------|------|
| 첫 접속 | 세션 시작 (`_session_start = now`) |
| 신규 슬롯 접속 | 새 채널 생성, 시작 전 구간 = NO_DATA(-1000) |
| 재접속 | 새 채널 추가 (기존 채널 보존) |
| 접속 끊김 | 채널 유지, `cur_y` 고정, 수평 연장 |

### NO_DATA 처리

- 채널 생성 전 구간: `-1000.0` (GLSL에서 렌더 스킵)
- GLSL: `if (y0 < -500.0 || y1 < -500.0) continue;`

---

## 파라미터 튜닝 가이드

### Speedscale (기울기 배율)

```
작은 값 (0.5–2)  → 전체적으로 완만한 그래프
중간 값 (2–5)   → 걷는 속도 기준 적당한 기울기
큰 값  (5–20)   → 조금만 움직여도 가파른 선
```

### Sessionduration (세션 길이)

```
3600  →  1시간짜리 세션 (테스트용)
28800 →  8시간짜리 세션 (기본값)
```
값이 클수록 같은 2000샘플에 더 긴 시간이 담김 → X축이 촘촘해짐

### uLineWidth (선 굵기)

```
0.001  얇은 선 / 0.002  기본값 / 0.005  굵은 선
```

---

## 슬롯 색상

| 슬롯 행 | 색상 | | 슬롯 행 | 색상 |
|---------|------|-|---------|------|
| 0 | Cyan | | 10 | Sky |
| 1 | Red | | 11 | Salmon |
| 2 | Green | | 12 | Mint |
| 3 | Yellow | | 13 | Lavender |
| 4 | Magenta | | 14 | Lime-Yellow |
| 5 | Teal | | 15 | Blue |
| 6 | Orange | | 16 | Rose |
| 7 | Purple | | 17 | Seafoam |
| 8 | Lime | | 18 | Tan |
| 9 | Pink | | 19 | Violet |

채널 순서(접속 순) 기준으로 색상이 순환 적용됨.

---

## 리셋

Script CHOP 상태 초기화 (TD Python 콘솔):
```python
import line_chop
line_chop._channels.clear()
line_chop._key_order.clear()
line_chop._slot_to_key.clear()
line_chop._session_start = None
line_chop._last_cook_t = None
line_chop._ch_count = 0
```

---

## 코드 수정 시 주의사항

- `HISTORY_LEN` 변경 → `line_chop.py`만 수정 (GLSL은 텍스처 크기 자동 감지)
- `_COLORS` / 팔레트 변경 → `line_chop.py` + `line_glsl.frag` 둘 다 수정
- `NO_DATA` 값 변경 → `line_chop.py` + `line_glsl.frag` 둘 다 수정 (GLSL의 -500.0 기준도 함께)
- **이 README는 코드와 항상 함께 수정한다**
