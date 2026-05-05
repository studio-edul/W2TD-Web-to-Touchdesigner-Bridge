# W2TD Fixed URL 설정 가이드

W2TD는 기본적으로 TD를 실행할 때마다 랜덤 Cloudflare 터널 URL이 생성됩니다.
**Fixed URL** 기능을 사용하면 항상 동일한 URL로 접속할 수 있어 QR 코드를 다시 스캔할 필요가 없습니다.

---

## 사전 준비 (Mac / Windows 공통)

1. **Cloudflare 계정 생성** — https://dash.cloudflare.com/sign-up (무료)
2. **도메인 등록 또는 연결** — Cloudflare에 도메인이 하나 이상 연결되어 있어야 합니다
3. **cloudflared CLI 설치**

---

## 1단계: cloudflared 설치

### macOS

```bash
brew install cloudflared
```

또는 Homebrew가 없다면:

```bash
# Apple Silicon
curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-darwin-amd64.tgz | tar xz
sudo mv cloudflared /usr/local/bin/
```

### Windows

```powershell
# winget 사용
winget install Cloudflare.cloudflared

# 또는 직접 다운로드
# https://github.com/cloudflare/cloudflared/releases/latest 에서 cloudflared-windows-amd64.exe 다운로드
# 다운받은 파일을 cloudflared.exe로 이름 변경 후 PATH가 잡힌 폴더에 배치
```

설치 확인:

```bash
cloudflared --version
```

---

## 2단계: Cloudflare 로그인 (인증)

### macOS

```bash
cloudflared tunnel login
```

브라우저가 열리면 Cloudflare 계정으로 로그인하고 도메인을 선택합니다.
인증 파일이 `~/.cloudflared/cert.pem`에 저장됩니다.

### Windows

```powershell
cloudflared tunnel login
```

브라우저가 열리면 동일하게 로그인합니다.
인증 파일이 `%USERPROFILE%\.cloudflared\cert.pem`에 저장됩니다.

---

## 3단계: 터널 생성

```bash
cloudflared tunnel create w2td-studio
```

- `w2td-studio`는 원하는 터널 이름으로 변경 가능
- 생성 후 출력되는 **Tunnel ID** (UUID)를 메모합니다

---

## 4단계: DNS 라우팅 설정

```bash
cloudflared tunnel route dns w2td-studio w2td.yourdomain.com
```

- `w2td.yourdomain.com` → Cloudflare에 등록된 도메인의 서브도메인
- 이 명령으로 CNAME 레코드가 자동 생성됩니다

---

## 5단계: 설정 파일 작성

### macOS

`~/.cloudflared/config.yml` 파일 생성:

```yaml
tunnel: w2td-studio
credentials-file: /Users/<사용자명>/.cloudflared/<터널ID>.json

ingress:
  - hostname: w2td.yourdomain.com
    service: http://localhost:9980
  - service: http_status:404
```

### Windows

`%USERPROFILE%\.cloudflared\config.yml` 파일 생성:

```yaml
tunnel: w2td-studio
credentials-file: C:\Users\<사용자명>\.cloudflared\<터널ID>.json

ingress:
  - hostname: w2td.yourdomain.com
    service: http://localhost:9980
  - service: http_status:404
```

> `<터널ID>.json`은 3단계에서 터널 생성 시 자동으로 만들어진 credentials 파일입니다.

---

## 6단계: TouchDesigner w2td_config 설정

`w2td_config` Table DAT에 다음 행을 추가합니다:

| key | value |
|-----|-------|
| `Fixedurl` | `1` |
| `Url` | `https://w2td-pro.studio-edul.com/?td=w2td.yourdomain.com` |
| `Tunnelname` | `w2td-studio` |

- `Fixedurl = 1` → 랜덤 터널 대신 고정 URL 모드 사용
- `Url` → QR 코드에 인코딩될 전체 URL
- `Tunnelname` → 3단계에서 만든 터널 이름

---

## 7단계: 터널 시작

### 방법 A — TouchDesigner에서 자동 시작 (Pro)

TD를 실행하면 `w2td_init.py`의 `start_fixed_tunnel()` 함수가 자동으로 `cloudflared tunnel run` 명령을 실행합니다.

수동 실행도 가능:

```python
# TD Textport에서
op('w2td_init').module.start_fixed_tunnel()
```

터널 종료:

```python
op('w2td_init').module.stop_tunnel()
```

### 방법 B — 터미널에서 수동 시작

```bash
cloudflared tunnel run w2td-studio
```

이 방법은 TD 외부에서 터널을 관리하고 싶을 때 사용합니다.

---

## 7-1단계: 시스템 서비스로 등록 (선택사항)

PC 부팅 시 자동으로 터널을 시작하려면:

### macOS (launchd)

```bash
sudo cloudflared service install
```

### Windows (서비스)

```powershell
cloudflared service install
```

> 서비스로 등록하면 TD와 별도로 터널이 항상 실행됩니다.

---

## 동작 확인

1. TD 시작 → Textport에서 `[W2TD] 터널 "w2td-studio" 연결 중...` 로그 확인
2. `[W2TD] Tunnel "w2td-studio" connected` 메시지가 나오면 성공
3. 모바일에서 QR 코드를 스캔하거나 고정 URL로 직접 접속

---

## 트러블슈팅

| 증상 | 해결 |
|------|------|
| `cloudflared binary not found` | cloudflared가 PATH에 없음. 설치 경로 확인 |
| `Tunnelname not set` | w2td_config에 `Tunnelname` 행 추가 |
| `Fixedurl=1 but Url is empty` | w2td_config에 `Url` 행 추가 |
| 터널 연결 후 502 에러 | TD Web Server DAT이 포트 9980에서 실행 중인지 확인 |
| 인증 만료 | `cloudflared tunnel login` 재실행 |

---

## 같은 URL로 두 대의 PC에서 동시에 터널을 열 수 있나요?

**기술적으로 가능하지만, W2TD에서는 사용하면 안 됩니다.**

Cloudflare Named Tunnel은 동일 터널 이름으로 여러 커넥터(replica)를 실행할 수 있습니다. 이 경우 Cloudflare가 트래픽을 **랜덤으로 로드밸런싱**합니다.

### 문제점

- 모바일 클라이언트의 WebSocket 연결이 **어느 PC로 갈지 예측 불가**
- 한 PC에 연결된 클라이언트의 센서 데이터가 **다른 PC에서는 보이지 않음**
- WebRTC 시그널링이 꼬여서 오디오/카메라 스트림 연결 실패
- 슬롯 상태가 PC마다 독립이므로 동일 슬롯 번호 충돌

### 권장 방안

| 시나리오 | 해결책 |
|----------|--------|
| 두 PC에서 각각 독립적으로 W2TD 사용 | **터널 2개** 생성 (예: `w2td-pc1`, `w2td-pc2`) + 서브도메인 2개 |
| 하나의 TD에 여러 모바일 연결 | 한 PC에서만 터널 실행 (최대 20대 동시 접속 지원) |
| 백업/페일오버 | 한 번에 한 PC에서만 실행. 메인 PC 꺼지면 백업 PC에서 시작 |

**결론: PC당 별도 터널 + 별도 서브도메인을 사용하세요.**

```bash
# PC 1
cloudflared tunnel create w2td-pc1
cloudflared tunnel route dns w2td-pc1 w2td-pc1.yourdomain.com

# PC 2
cloudflared tunnel create w2td-pc2
cloudflared tunnel route dns w2td-pc2 w2td-pc2.yourdomain.com
```
