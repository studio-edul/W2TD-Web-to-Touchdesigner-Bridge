import json

GITHUB_PAGES_URL = 'https://studio-edul.github.io/Web-Osc-Bridge/'
# Default - overridden by config_table DAT at init_tables() time
MAX_CLIENTS = 20


SENSOR_COLS = [
	'slot', 'connected',
	'ax', 'ay', 'az',
	'ga', 'gb', 'gg',
	'oa', 'ob', 'og',
	'lat', 'lon',
	'touch_count',
	'trig',
]

# ── Persistent state (survives module reload via op('/').store/fetch) ──────────
# These are stored in TD's global root op so module reloads don't reset them.

def _slots():
	"""Returns client_slots dict {addr: slot}."""
	return op('/').fetch('wob_client_slots', {})

def _free():
	"""Returns free_slots list."""
	return op('/').fetch('wob_free_slots', list(range(1, MAX_CLIENTS + 1)))

def _touch():
	"""Returns touch_count dict {slot: count}."""
	return op('/').fetch('wob_touch_count', {})

def _save_slots(d):
	op('/').store('wob_client_slots', d)

def _save_free(lst):
	op('/').store('wob_free_slots', lst)

def _save_touch(d):
	op('/').store('wob_touch_count', d)

def _find_row(t, slot):
	"""Return the row index in sensor_table whose 'slot' column matches slot, or None."""
	for r in range(1, t.numRows):
		try:
			if int(t[r, 'slot']) == slot:
				return r
		except Exception:
			pass
	return None

# ──────────────────────────────────────────────────────────────────────────────

def _read_config():
	"""Read settings from wob_config Table DAT (key | value)."""
	cfg = op('wob_config')
	if cfg is None:
		return {}
	out = {}
	for r in range(1, cfg.numRows):
		try:
			out[str(cfg[r, 0])] = str(cfg[r, 1])
		except Exception:
			pass
	return out


def init_tables():
	"""Initialize sensor_table and touch_table DATs. Called from Execute DAT onStart()."""
	global MAX_CLIENTS

	cfg = _read_config()
	if 'max_clients' in cfg:
		try:
			MAX_CLIENTS = max(1, int(cfg['max_clients']))
		except ValueError:
			pass

	# Reset persistent state
	_save_slots({})
	_save_free(list(range(1, MAX_CLIENTS + 1)))
	_save_touch({})

	t = op('sensor_table')
	if t is not None:
		t.clear()
		t.appendRow(SENSOR_COLS)
		print(f'[WOB] sensor_table initialized (dynamic rows, max {MAX_CLIENTS} slots)')
	else:
		print('[WOB] sensor_table DAT not found - create a Table DAT named "sensor_table"')

	tt = op('touch_table')
	if tt is not None:
		tt.clear()
		tt.appendRow(['slot', 'touch_id', 'x', 'y', 'state'])
		print('[WOB] touch_table initialized')
	else:
		print('[WOB] touch_table DAT not found - create a Table DAT named "touch_table"')


def _config_msg(cfg):
	"""Build config JSON dict from wob_config values."""
	return {
		'type':               'config',
		'sample_rate':        int(cfg.get('sample_rate', 30)),
		'wake_lock':          int(cfg.get('wake_lock', 1)),
		'haptic':             int(cfg.get('haptic', 1)),
		'sensor_motion':      int(cfg.get('sensor_motion', 1)),
		'sensor_orientation': int(cfg.get('sensor_orientation', 1)),
		'sensor_geolocation': int(cfg.get('sensor_geolocation', 0)),
		'sensor_touch':       int(cfg.get('sensor_touch', 1)),
		'dev_mode':           int(cfg.get('dev_mode', 1)),
		'sensor_camera':      int(cfg.get('sensor_camera', 0)),
		'sensor_microphone':  int(cfg.get('sensor_microphone', 0)),
		'audio_echo_cancellation':  int(cfg.get('audio_echo_cancellation', 0)),
		'audio_noise_suppression':  int(cfg.get('audio_noise_suppression', 0)),
		'audio_auto_gain':          int(cfg.get('audio_auto_gain', 0)),
	}


def broadcast_config(webServerDAT):
	"""Push updated config to all connected clients.
	Call from TD script after editing wob_config:
	    op('web_server_dat').module.broadcast_config(op('web_server_dat'))
	wob_config keys: sample_rate, wake_lock, haptic, sensors, dev_mode, camera, microphone
	"""
	cfg = _read_config()
	msg = json.dumps(_config_msg(cfg))
	for addr in list(_slots().keys()):
		try:
			webServerDAT.webSocketSendText(addr, msg)
		except Exception:
			pass
	print(f'[WOB] Config broadcast -> {len(_slots())} clients')


def onHTTPRequest(webServerDAT, request, response):
	"""Redirect to GitHub Pages with TD address as param."""
	stored_url = op('/').fetch('wob_url', '')
	host = stored_url.replace('https://', '').replace('http://', '').strip()
	if not host:
		host = request.get('headers', {}).get('Host', '')
	print(f'[WOB] HTTP request -> host: {host}')
	redirect_url = GITHUB_PAGES_URL + ('?td=' + host if host else '')

	response['statusCode'] = 200
	response['statusReason'] = 'OK'
	response['data'] = f'''<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>WOB</title>
  <style>
    body {{ font-family: sans-serif; text-align: center; padding: 40px 20px;
           background: #111; color: #fff; }}
    h1 {{ color: #4caf50; font-size: 2em; margin-bottom: 12px; }}
    p {{ color: #aaa; margin: 8px 0; }}
    a {{ color: #4caf50; font-size: 1.1em; word-break: break-all; }}
  </style>
  <script>
    window.location.href = '{redirect_url}';
  </script>
</head>
<body>
  <h1>&#10003; WOB</h1>
  <p>Redirecting...</p>
  <p><a href="{redirect_url}">Tap here if not redirected</a></p>
</body>
</html>'''
	return response


def onWebSocketOpen(webServerDAT, client):
	try:
		# Store web server DAT path so webrtc_callbacks.py can find it
		op('/').store('wob_webserver_op', webServerDAT.path)

		addr = str(client)
		free = _free()

		if not free:
			print(f'[WOB] No slots available (max {MAX_CLIENTS}). Rejected: {addr}')
			webServerDAT.webSocketSendText(client, json.dumps({
				'type': 'rejected',
				'reason': f'Server is currently full ({MAX_CLIENTS} devices connected). Please try again in a moment.',
			}))
			return

		slot = free.pop(0)
		slots = _slots()
		slots[addr] = slot
		_save_slots(slots)
		_save_free(free)

		t = op('sensor_table')
		if t is not None:
			t.appendRow([slot, 1] + [0.0] * (len(SENSOR_COLS) - 2))

		print(f'[WOB] Connected -> slot {slot} | {addr} | {MAX_CLIENTS - len(free)} active')
		webServerDAT.webSocketSendText(client, json.dumps({'type': 'ack', 'slot': slot}))

		# Push current config to the newly connected client
		cfg = _read_config()
		webServerDAT.webSocketSendText(client, json.dumps(_config_msg(cfg)))
	except Exception as e:
		print(f'[WOB] ERROR in onWebSocketOpen: {e}')


def onWebSocketClose(webServerDAT, client):
	addr = str(client)
	slots = _slots()
	slot = slots.pop(addr, None)

	if slot is None:
		return

	free = _free()
	free.append(slot)
	free.sort()
	_save_slots(slots)
	_save_free(free)

	touch = _touch()
	touch.pop(slot, None)
	_save_touch(touch)

	t = op('sensor_table')
	if t is not None:
		row = _find_row(t, slot)
		if row is not None:
			t.deleteRow(row)

	tt = op('touch_table')
	if tt is not None:
		rows_to_delete = [
			r for r in range(1, tt.numRows)
			if int(tt[r, 'slot']) == slot
		]
		for r in reversed(rows_to_delete):
			tt.deleteRow(r)

	# Clean up WebRTC state for this slot
	conn_id = op('/').fetch(f'wob_webrtc_slot_to_uuid_{slot}', None)
	if conn_id:
		wrtc = op('webrtc_dat')
		if wrtc is not None:
			try:
				wrtc.closeConnection(conn_id)
			except Exception:
				pass
		op('/').store(f'wob_webrtc_addr_{conn_id}', None)
		op('/').store(f'wob_webrtc_slot_to_uuid_{slot}', None)

	print(f'[WOB] Disconnected -> slot {slot} | {addr} | {MAX_CLIENTS - len(free)} active')


def onWebSocketReceiveText(webServerDAT, client, data):
	addr = str(client)
	slots = _slots()
	slot = slots.get(addr)

	if slot is None:
		free = _free()
		if not free:
			return
		slot = free.pop(0)
		slots[addr] = slot
		_save_slots(slots)
		_save_free(free)
		t2 = op('sensor_table')
		if t2 is not None and _find_row(t2, slot) is None:
			t2.appendRow([slot, 1] + [0.0] * (len(SENSOR_COLS) - 2))
		print(f'[WOB] Recovered slot {slot} for {addr}')

	try:
		msg = json.loads(data)
	except Exception:
		return

	msg_type = msg.get('type')

	if msg_type == 'sensor':
		t = op('sensor_table')
		if t is None:
			return
		row = _find_row(t, slot)
		if row is None:
			return
		g = msg.get
		# Consume pending trig pulse (1 for one packet, then resets to 0)
		trig_key = f'wob_trig_{slot}'
		trig = op('/').fetch(trig_key, 0)
		if trig:
			op('/').store(trig_key, 0)
		t.replaceRow(row, [
			slot, 1,
			g('ax', 0), g('ay', 0), g('az', 0),
			g('ga', 0), g('gb', 0), g('gg', 0),
			g('oa', 0), g('ob', 0), g('og', 0),
			g('lat', 0), g('lon', 0),
			_touch().get(slot, 0),
			trig,
		])

	elif msg_type == 'touch':
		count = msg.get('count', 0)
		touch = _touch()
		touch[slot] = count
		_save_touch(touch)

		t = op('sensor_table')
		if t is not None:
			row = _find_row(t, slot)
			if row is not None:
				t[row, 'touch_count'] = count

		tt = op('touch_table')
		if tt is not None:
			rows_to_delete = [
				r for r in range(1, tt.numRows)
				if int(tt[r, 'slot']) == slot
			]
			for r in reversed(rows_to_delete):
				tt.deleteRow(r)
			g = msg.get
			for i in range(count):
				tt.appendRow([slot, i, g(f't{i}x', 0), g(f't{i}y', 0), g(f't{i}s', 0)])

	elif msg_type == 'trigger':
		op('/').store(f'wob_trig_{slot}', 1)

	elif msg_type == 'hello':
		print(f'[WOB] Hello from slot {slot} - OK')

	elif msg_type == 'webrtc_offer':
		sdp = msg.get('sdp')
		if not sdp:
			return
		wrtc = op('webrtc_dat')
		if wrtc is None:
			print('[WOB] webrtc_dat not found — create a WebRTC DAT named "webrtc_dat"')
			return
		try:
			conn_id = wrtc.openConnection()
			op('/').store(f'wob_webrtc_addr_{conn_id}', addr)
			op('/').store(f'wob_webrtc_slot_to_uuid_{slot}', conn_id)
			wrtc.setRemoteDescription(conn_id, 'offer', sdp)
			wrtc.createAnswer(conn_id)
			print(f'[WOB WebRTC] Offer received from slot {slot}, conn_id={conn_id}, creating answer...')
		except Exception as e:
			print(f'[WOB WebRTC] Offer handling error: {e}')

	elif msg_type == 'webrtc_ice':
		candidate = msg.get('candidate')
		if not candidate:
			return
		wrtc = op('webrtc_dat')
		if wrtc is None:
			return
		conn_id = op('/').fetch(f'wob_webrtc_slot_to_uuid_{slot}', None)
		if conn_id is None:
			return
		line_index = int(msg.get('sdpMLineIndex', 0))
		sdp_mid = msg.get('sdpMid', '')
		try:
			wrtc.addIceCandidate(conn_id, candidate, line_index, sdp_mid)
		except Exception as e:
			print(f'[WOB WebRTC] addIceCandidate error: {e}')
