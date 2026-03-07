# W2TD Remote Client Mode (Archived/Development)

## 아키텍처 및 구현 의도
집이나 원격지에서 전시장(Host) TD로 접속하여 실시간 모바일 센서 데이터와 터치 이벤트를 릴레이(Relay) 받기 위한 기능입니다. 
Cloudflare 터널(`wss://...`)을 통해 원격 접속한 TD 인스턴스가 관람객 데이터(`sensor_table`, `touch_table`)를 그대로 미러링하는 것을 목표로 설계되었습니다.

## 문제점 및 롤백 사유
이 기능을 활성화하고 원격 PC에서 접속하는 순간, Host PC 측에서 **기존 모바일 기기들의 연결이 초기화되고 영상 송출이 뚝뚝 끊기는 치명적인 문제**가 발생했습니다.

**원인 분석:**
1. **신원 혼란 (Slot Hijacking):** 원격 접속한 TD(Client) 측에서 WebSocket으로 연결 시, TouchDesigner 내부적으로 혹은 Cloudflare 터널 자체적인 Ping/Pong 등의 메타 패킷이 Host로 전송됩니다. 이때 Host의 `onWebSocketReceiveText` 구조상, 명확하게 핸들링되지 않은 패킷 도착 시 새로운 빈 자리(Slot) 하나를 할당해 버리는 설계가 있습니다.
2. **Web Render TOP 초기화 연쇄 작용:** 의도치 않은 패킷으로 인해 원격 장비가 새로운 관람객으로 취급되어 `sensor_table` 행(Row) 개수가 변경됩니다. `cam_render_sync.py` 스크립트는 `sensor_table`의 변동을 감지하고 모바일 카메라 표시를 위한 `web_render_top` 인스턴스들을 일괄 재생성·초기화합니다.
3. **연결 붕괴 (Video Stream Drops):** `web_render_top`이 재생성되면, 기존 핸드폰 관람객들과 연결되어 있던 WebRTC 카메라(Webcam) 스트리밍 소켓이 순간적으로 끊기게 되어 영상 피드가 멈추고 센서 데이터 수집도 중단됩니다.

## 향후 재개발 시 고려 사항
- **별도의 독립된 WebSocket 경로 확보:** 기존 관람객 데이터가 흐르는 웹소켓 통신망(`web_server_dat`)에 Client TD를 접속시키는 대신, TD 대 TD 통신을 위한 별도의 웹소켓 터널을 여는 것이 훨씬 안정적입니다.
- **엄격한 인증 및 Slot 제외 로직 설계:** 기존망을 사용해야 한다면, Web Server DAT의 `onWebSocketOpen`이나 초반 핸드셰이크 과정에서 철저하게 Remote TD임을 증명하는 인증 단계를 거친 거나 포트를 다르게 배정하여 모바일 기기 풀(`_slots()`) 계산에서 완전히 배제해야 합니다.

## 작성했던 코드(보존용)
이 기능 구현을 위해 작성되었으나 롤백된 주요 스니펫들입니다.

### 1. `w2td_remote_callbacks.py` (Client 수신부 DAT)
```python
import json

def _w2td_base():
	try: return parent(1)
	except NameError: pass
	return op('W2TD') # Pro 버전은 W2TD_Pro

def _op(path_suffix, fallback_name=None):
	base = _w2td_base()
	if base:
		o = base.op(path_suffix)
		if o is not None:
			return o
	return op(fallback_name or path_suffix.split('/')[-1])

def _find_row(t, slot):
	for r in range(1, t.numRows):
		try:
			if int(t[r, 'slot']) == slot:
				return r
		except Exception:
			pass
	return None

def onConnect(dat):
	dat.sendText(json.dumps({"type": "hello", "role": "remote_td"}))

def onDisconnect(dat):
	t = _op('sensor_table')
	if t is not None:
		t.clear(keepFirstRow=True)
	tt = _op('touch_table')
	if tt is not None:
		tt.clear(keepFirstRow=True)

def onReceiveText(dat, rowIndex, message):
	try:
		msg = json.loads(message)
	except Exception:
		return
		
	msg_type = msg.get('type')
	slot = msg.get('slot')
	if slot is None: return
	
	if msg_type == 'sensor':
		t = _op('sensor_table')
		if t is None: return
		row = _find_row(t, slot)
		if row is None:
			client_name = msg.get('name', f'Slot {slot}')
			t.appendRow([slot, 1, client_name] + [0.0] * 19)
			row = t.numRows - 1
			
		g = msg.get
		t.replaceRow(row, [
			slot, 1, t[row, 'name'].val,
			g('ax', 0), g('ay', 0), g('az', 0),
			g('ga', 0), g('gb', 0), g('gg', 0),
			g('oa', 0), g('ob', 0), g('og', 0),
			g('lat', 0), g('lon', 0),
			t[row, 'touch_count'].val,
			t[row, 'css_width'].val, t[row, 'css_height'].val,
			t[row, 'physical_width'].val, t[row, 'physical_height'].val,
			t[row, 'screen_width'].val, t[row, 'screen_height'].val,
			t[row, 'device_pixel_ratio'].val
		])
		
	elif msg_type == 'touch':
		tt = _op('touch_table')
		if tt is not None:
			rows_to_delete = [r for r in range(1, tt.numRows) if int(tt[r, 'slot']) == slot]
			for r in reversed(rows_to_delete):
				tt.deleteRow(r)
			count = msg.get('count', 0)
			g = msg.get
			for i in range(count):
				tt.appendRow([slot, i, g(f't{i}x', 0), g(f't{i}y', 0), g(f't{i}s', 0)])
				
		t = _op('sensor_table')
		if t is not None:
			row = _find_row(t, slot)
			if row is not None:
				t[row, 'touch_count'] = count
```

### 2. `callbacks.py` (Host 송신부 릴레이 로직)
```python
def _relay_to_remotes(webServerDAT, msg_dict, slot):
	"""Relay message to all registered remote_td listeners."""
	listeners = op('/').fetch('w2td_remote_listeners', [])
	if not listeners:
		return
	msg_dict['slot'] = slot
	try:
		text = json.dumps(msg_dict)
		for rv in listeners:
			try:
				webServerDAT.webSocketSendText(rv, text)
			except Exception:
				pass
	except Exception:
		pass

def onWebSocketReceiveText(webServerDAT, client, data):
	addr = str(client)

	# Remote TD 연결 식별 및 수집 방지
	if msg.get('type') == 'hello' and msg.get('role') == 'remote_td':
		listeners = op('/').fetch('w2td_remote_listeners', [])
		if addr not in listeners:
			listeners.append(addr)
			op('/').store('w2td_remote_listeners', listeners)
		try:
			webServerDAT.webSocketSendText(addr, json.dumps({'type': 'ack', 'role': 'remote_td', 'td_version': W2TD_VERSION}))
		except Exception:
			pass
		return

	# Remote 패킷 무시 보호 코드
	if addr in op('/').fetch('w2td_remote_listeners', []):
		return
```

### 3. Server / Client 스위칭 (config_watch.py)
```python
	# w2td_config 테이블의 'Mode' 값을 읽어서 설정
	mode_str = 'Server'
	for k, v in cfg.items():
		if k.lower() == 'mode':
			mode_str = v.strip()
			
	try:
		web_node = _op('web_server_dat')
		remote_node = _op('w2td_remote')
		is_client = (mode_str.lower() == 'client')
		
		# .expr을 초기화하여 이전 잔재가 에러를 발생시키지 않도록 방지
		if web_node:
			web_node.par.active.expr = ''
			web_node.par.active = not is_client
		if remote_node:
			remote_node.par.active.expr = ''
			remote_node.par.active = is_client
	except Exception as e:
		pass
```

### 4. Client 모드 시 터널 방지 (w2td_init.py)
```python
	# Skip tunnel and QR if in Client (Remote) mode
	mode_val = cfg.get('Mode') or cfg.get('mode')
	if mode_val and mode_val.strip().lower() == 'client':
		print('[W2TD] Client mode active. Skipping Cloudflare tunnel and QR generation.')
		return
```
