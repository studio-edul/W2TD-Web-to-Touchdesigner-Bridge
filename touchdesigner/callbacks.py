import json

GITHUB_PAGES_URL = 'https://studio-edul.github.io/Web-Osc-Bridge/'
# Default - overridden by config_table DAT at init_tables() time
MAX_CLIENTS = 20


SENSOR_COLS = [
	'slot', 'connected', 'name',
	'ax', 'ay', 'az',
	'ga', 'gb', 'gg',
	'oa', 'ob', 'og',
	'lat', 'lon',
	'touch_count',
	'trig',
	'css_width', 'css_height',
	'physical_width', 'physical_height',
	'screen_width', 'screen_height',
	'device_pixel_ratio',
]

# ── Persistent state (survives module reload via op('/').store/fetch) ──────────
# These are stored in TD's global root op so module reloads don't reset them.

def _slots():
	"""Returns client_slots dict {addr: slot}."""
	return op('/').fetch('wob_client_slots', {})

def _free():
	"""Returns free_slots list."""
	return op('/').fetch('wob_free_slots', list(range(1, MAX_CLIENTS + 1)))

def _client_names():
	"""Returns client_names dict {slot: name}."""
	return op('/').fetch('wob_client_names', {})

def _touch():
	"""Returns touch_count dict {slot: count}."""
	return op('/').fetch('wob_touch_count', {})

def _save_slots(d):
	op('/').store('wob_client_slots', d)

def _save_free(lst):
	op('/').store('wob_free_slots', lst)

def _save_touch(d):
	op('/').store('wob_touch_count', d)

def _save_client_names(d):
	op('/').store('wob_client_names', d)

def _find_row(t, slot):
	"""Return the row index in sensor_table whose 'slot' column matches slot, or None."""
	for r in range(1, t.numRows):
		try:
			if int(t[r, 'slot']) == slot:
				return r
		except Exception:
			pass
	return None

def _cam_receiver_addr():
	"""Returns stored cam_receiver WebSocket address, or None."""
	return op('/').fetch('wob_cam_receiver_addr', None)

def _save_cam_receiver_addr(addr):
	op('/').store('wob_cam_receiver_addr', addr)

def _addr_for_slot(slot):
	"""Return WebSocket addr for a given slot number, or None."""
	for addr, s in _slots().items():
		if s == slot:
			return addr
	return None

def _release_slot(addr, slot):
	"""Return a slot to the free pool and remove sensor_table row."""
	slots = _slots()
	slots.pop(addr, None)
	_save_slots(slots)
	free = _free()
	if slot not in free:
		free.append(slot)
		free.sort()
	_save_free(free)
	t = op('sensor_table')
	if t is not None:
		row = _find_row(t, slot)
		if row is not None:
			t.deleteRow(row)

def _handle_cam_receiver_msg(webServerDAT, addr, msg):
	"""Process messages from cam_receiver.html (Web Render TOP)."""
	msg_type = msg.get('type')

	if msg_type == 'cam_answer':
		sdp = msg.get('sdp')
		slot = msg.get('slot')
		if not sdp or slot is None:
			return
		mobile_addr = _addr_for_slot(slot)
		if mobile_addr is None:
			print(f'[WOB Cam] cam_answer: no mobile addr for slot {slot}')
			return
		try:
			webServerDAT.webSocketSendText(mobile_addr, json.dumps({
				'type': 'webrtc_answer_cam',
				'sdp': sdp,
			}))
			print(f'[WOB Cam] cam_answer relayed -> slot {slot}')
		except Exception as e:
			print(f'[WOB Cam] cam_answer relay error: {e}')

	elif msg_type == 'cam_ice':
		candidate = msg.get('candidate')
		slot = msg.get('slot')
		if not candidate or slot is None:
			return
		mobile_addr = _addr_for_slot(slot)
		if mobile_addr is None:
			return
		try:
			webServerDAT.webSocketSendText(mobile_addr, json.dumps({
				'type': 'webrtc_ice_cam',
				'candidate': candidate,
				'sdpMLineIndex': msg.get('sdpMLineIndex', 0),
				'sdpMid': msg.get('sdpMid', ''),
			}))
		except Exception as e:
			print(f'[WOB Cam] cam_ice relay error: {e}')

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
			MAX_CLIENTS = max(1, int(cfg['max_clients']))  # Minimum 1, can be any positive number
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
	out = {
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
		'sensor_microphone':  int(cfg.get('sensor_microphone', 1)),
		'audio_echo_cancellation':  int(cfg.get('audio_echo_cancellation', 0)),
		'audio_noise_suppression':  int(cfg.get('audio_noise_suppression', 0)),
		'audio_auto_gain':          int(cfg.get('audio_auto_gain', 0)),
	}
	ice_srv = cfg.get('ice_servers', '').strip()
	if ice_srv:
		out['ice_servers'] = ice_srv
	# 'relay'로 명시된 경우에만 제한. 미설정(기본값)이면 전송 안 함 → 브라우저 기본 'all' 사용
	if cfg.get('ice_transport_policy', '').strip() == 'relay':
		out['ice_transport_policy'] = 'relay'
	return out


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


def send_haptic_to_client(webServerDAT, slot, pattern):
	"""Send haptic feedback pattern to a specific client.
	
	Args:
		webServerDAT: Web Server DAT operator
		slot: Client slot number (int)
		pattern: List of vibration durations in milliseconds
			Example: [200, 100, 200] = vibrate 200ms, pause 100ms, vibrate 200ms
			Single value: [200] = vibrate 200ms once
	
	Usage in TD:
		op('web_server_dat').module.send_haptic_to_client(op('web_server_dat'), 1, [200, 100, 200])
		op('web_server_dat').module.send_haptic_to_all(op('web_server_dat'), [200])
	"""
	addr = _addr_for_slot(slot)
	if addr is None:
		print(f'[WOB Haptic] No client found for slot {slot}')
		return False
	
	if not isinstance(pattern, list) or len(pattern) == 0:
		print(f'[WOB Haptic] Invalid pattern: {pattern}')
		return False
	
	try:
		msg = json.dumps({
			'type': 'haptic',
			'pattern': pattern
		})
		webServerDAT.webSocketSendText(addr, msg)
		print(f'[WOB Haptic] Sent pattern {pattern} to slot {slot}')
		return True
	except Exception as e:
		print(f'[WOB Haptic] Send failed for slot {slot}: {e}')
		return False


def send_haptic_to_all(webServerDAT, pattern):
	"""Send haptic feedback pattern to all connected clients.
	
	Args:
		webServerDAT: Web Server DAT operator
		pattern: List of vibration durations in milliseconds
	
	Usage in TD:
		op('web_server_dat').module.send_haptic_to_all(op('web_server_dat'), [200, 100, 200])
	"""
	success_count = 0
	for slot in _slots().values():
		if send_haptic_to_client(webServerDAT, slot, pattern):
			success_count += 1
	print(f'[WOB Haptic] Sent pattern {pattern} to {success_count} clients')
	return success_count


def send_haptic_state(webServerDAT, slot, state):
	"""Send haptic state (0 or 1) to a specific client.
	
	Args:
		webServerDAT: Web Server DAT operator
		slot: Client slot number (int)
		state: Vibration state (0 = stop, 1 = vibrate continuously)
	
	Usage in TD:
		op('web_server_dat').module.send_haptic_state(op('web_server_dat'), 1, 1)  # slot 1 vibrate
		op('web_server_dat').module.send_haptic_state(op('web_server_dat'), 1, 0)  # slot 1 stop
	"""
	addr = _addr_for_slot(slot)
	if addr is None:
		return False
	
	if state not in (0, 1):
		print(f'[WOB Haptic] Invalid state: {state} (must be 0 or 1)')
		return False
	
	try:
		msg = json.dumps({
			'type': 'haptic',
			'state': state
		})
		webServerDAT.webSocketSendText(addr, msg)
		return True
	except Exception as e:
		print(f'[WOB Haptic] Send state failed for slot {slot}: {e}')
		return False


def broadcast_haptic_from_chop(webServerDAT, chop_name='wob_haptic'):
	"""Read haptic CHOP and send state to all connected clients.
	
	CHOP structure:
		- Channel names: 'slot1', 'slot2', ... or 'ch1', 'ch2', ... or '1', '2', ...
		- Values: 0 = stop vibration, 1 = vibrate continuously
		- Non-zero values are treated as 1
	
	Args:
		webServerDAT: Web Server DAT operator
		chop_name: Name of the CHOP operator (default: 'wob_haptic')
	
	Usage in TD (Timer CHOP or Execute DAT):
		op('web_server_dat').module.broadcast_haptic_from_chop(op('web_server_dat'))
		op('web_server_dat').module.broadcast_haptic_from_chop(op('web_server_dat'), 'my_haptic_chop')
	
	Setup:
		1. Create a Constant CHOP or any CHOP named 'wob_haptic' (or custom name)
		2. Add channels: 'slot1', 'slot2', ... (or 'ch1', 'ch2', ... or '1', '2', ...)
		3. Connect Timer CHOP or Execute DAT to call this function periodically
	"""
	chop = op(chop_name)
	if chop is None:
		return 0
	
	success_count = 0
	active_slots = _slots().values()
	
	# Try different channel naming conventions
	for slot in active_slots:
		state = 0
		
		# Try channel names: 'slot1', 'slot2', ...
		channel_name = f'slot{slot}'
		if channel_name in chop.chans:
			try:
				val = chop[channel_name][0]
				state = 1 if val != 0 else 0
			except Exception:
				pass

		# Fallback: try 'ch1', 'ch2', ...
		if state == 0 and f'ch{slot}' in chop.chans:
			try:
				val = chop[f'ch{slot}'][0]
				state = 1 if val != 0 else 0
			except Exception:
				pass

		# Fallback: try numeric channel names '1', '2', ...
		if state == 0 and str(slot) in chop.chans:
			try:
				val = chop[str(slot)][0]
				state = 1 if val != 0 else 0
			except Exception:
				pass

		# Fallback: try channel index (slot-1 as index)
		if state == 0 and slot - 1 < len(chop.chans):
			try:
				val = chop[slot - 1][0]
				state = 1 if val != 0 else 0
			except Exception:
				pass
		
		# Send state to client
		if send_haptic_state(webServerDAT, slot, state):
			success_count += 1
	
	return success_count


def send_heartbeat(webServerDAT, slot=None):
	"""Send heartbeat ping to a specific client or all clients.
	
	Args:
		webServerDAT: Web Server DAT operator
		slot: Client slot number (int). If None, sends to all clients.
	
	Usage in TD (Timer CHOP or Execute DAT):
		op('web_server_dat').module.send_heartbeat(op('web_server_dat'))  # all clients
		op('web_server_dat').module.send_heartbeat(op('web_server_dat'), 1)  # slot 1 only
	"""
	if slot is not None:
		addr = _addr_for_slot(slot)
		if addr is None:
			return False
		try:
			webServerDAT.webSocketSendText(addr, json.dumps({'type': 'ping'}))
			return True
		except Exception:
			return False
	else:
		# Send to all clients
		success_count = 0
		for addr in list(_slots().keys()):
			try:
				webServerDAT.webSocketSendText(addr, json.dumps({'type': 'ping'}))
				success_count += 1
			except Exception:
				pass
		return success_count


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
			# Default name: Slot {slot}
			default_name = f'Slot {slot}'
			# Initialize with default screen info (will be updated when screen_info message arrives)
			t.appendRow([slot, 1, default_name] + [0.0] * (len(SENSOR_COLS) - 3))

		print(f'[WOB] Connected -> slot {slot} | {addr} | {len(slots)}/{MAX_CLIENTS} active')
		webServerDAT.webSocketSendText(client, json.dumps({'type': 'ack', 'slot': slot}))

		# Push current config to the newly connected client
		cfg = _read_config()
		webServerDAT.webSocketSendText(client, json.dumps(_config_msg(cfg)))
	except Exception as e:
		print(f'[WOB] ERROR in onWebSocketOpen: {e}')


def onWebSocketClose(webServerDAT, client):
	addr = str(client)

	# cam_receiver disconnect
	if addr == _cam_receiver_addr():
		_save_cam_receiver_addr(None)
		print(f'[WOB Cam] cam_receiver disconnected: {addr}')
		return

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

		print(f'[WOB] Disconnected -> slot {slot} | {addr} | {len(slots)}/{MAX_CLIENTS} active')


def onWebSocketReceiveText(webServerDAT, client, data):
	addr = str(client)

	# cam_receiver.html messages are routed separately (no slot)
	if addr == _cam_receiver_addr():
		try:
			msg = json.loads(data)
		except Exception:
			return
		_handle_cam_receiver_msg(webServerDAT, addr, msg)
		return

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
			# Get client name if exists
			names = _client_names()
			client_name = names.get(slot, f'Slot {slot}')
			t2.appendRow([slot, 1, client_name] + [0.0] * (len(SENSOR_COLS) - 3))
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
		# Get client name
		names = _client_names()
		client_name = names.get(slot, f'Slot {slot}')
		
		# Get screen resolution (stored separately)
		screen_info = op('/').fetch(f'wob_screen_{slot}', {})
		css_width = screen_info.get('width', 0)
		css_height = screen_info.get('height', 0)
		physical_width = screen_info.get('physicalWidth', 0)
		physical_height = screen_info.get('physicalHeight', 0)
		screen_width = screen_info.get('screenWidth', 0)
		screen_height = screen_info.get('screenHeight', 0)
		device_pixel_ratio = screen_info.get('devicePixelRatio', 1.0)
		
		t.replaceRow(row, [
			slot, 1, client_name,
			g('ax', 0), g('ay', 0), g('az', 0),
			g('ga', 0), g('gb', 0), g('gg', 0),
			g('oa', 0), g('ob', 0), g('og', 0),
			g('lat', 0), g('lon', 0),
			_touch().get(slot, 0),
			trig,
			css_width, css_height,
			physical_width, physical_height,
			screen_width, screen_height,
			device_pixel_ratio,
		])
		# Send ack signal to indicate data received
		try:
			webServerDAT.webSocketSendText(addr, json.dumps({'type': 'data_ack'}))
		except Exception:
			pass

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
		# Send ack signal for touch data
		try:
			webServerDAT.webSocketSendText(addr, json.dumps({'type': 'data_ack'}))
		except Exception:
			pass

	elif msg_type == 'trigger':
		op('/').store(f'wob_trig_{slot}', 1)

	elif msg_type == 'hello':
		role = msg.get('role', '')
		if role == 'cam_receiver':
			# cam_receiver.html identified itself — return its slot and track it
			_release_slot(addr, slot)
			_save_cam_receiver_addr(addr)
			print(f'[WOB Cam] cam_receiver registered: {addr}')
		else:
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

	elif msg_type == 'webrtc_offer_cam':
		# Camera offer from mobile → relay to cam_receiver as cam_offer
		sdp = msg.get('sdp')
		if not sdp:
			return
		receiver_addr = _cam_receiver_addr()
		if receiver_addr is None:
			print('[WOB Cam] webrtc_offer_cam received but no cam_receiver connected')
			return
		try:
			webServerDAT.webSocketSendText(receiver_addr, json.dumps({
				'type': 'cam_offer',
				'slot': slot,
				'sdp': sdp,
			}))
			print(f'[WOB Cam] cam_offer relayed to receiver (slot {slot})')
		except Exception as e:
			print(f'[WOB Cam] cam_offer relay error: {e}')

	elif msg_type == 'webrtc_ice_cam':
		# ICE from mobile → relay to cam_receiver
		candidate = msg.get('candidate')
		if not candidate:
			return
		receiver_addr = _cam_receiver_addr()
		if receiver_addr is None:
			return
		try:
			webServerDAT.webSocketSendText(receiver_addr, json.dumps({
				'type': 'cam_ice',
				'slot': slot,
				'candidate': candidate,
				'sdpMLineIndex': msg.get('sdpMLineIndex', 0),
				'sdpMid': msg.get('sdpMid', ''),
			}))
		except Exception as e:
			print(f'[WOB Cam] webrtc_ice_cam relay error: {e}')

	elif msg_type == 'ping':
		# Heartbeat ping from mobile → respond with pong
		try:
			webServerDAT.webSocketSendText(addr, json.dumps({'type': 'pong'}))
		except Exception:
			pass

	elif msg_type == 'client_name':
		# Client name update from mobile
		client_name = msg.get('name', '').strip()
		if not client_name:
			client_name = f'Slot {slot}'
		
		# Store name
		names = _client_names()
		names[slot] = client_name
		_save_client_names(names)
		
		# Update sensor_table
		t = op('sensor_table')
		if t is not None:
			row = _find_row(t, slot)
			if row is not None:
				t[row, 'name'] = client_name
		
		print(f'[WOB] Client name updated: slot {slot} -> {client_name}')

	elif msg_type == 'screen_info':
		# Screen resolution info from mobile
		css_width = msg.get('width', 0)  # CSS viewport width (web-optimized)
		css_height = msg.get('height', 0)  # CSS viewport height (web-optimized)
		physical_width = msg.get('physicalWidth', 0)  # Physical pixel width
		physical_height = msg.get('physicalHeight', 0)  # Physical pixel height
		screen_width = msg.get('screenWidth', 0)  # Device screen width
		screen_height = msg.get('screenHeight', 0)  # Device screen height
		device_pixel_ratio = msg.get('devicePixelRatio', 1.0)
		
		# Store screen info
		screen_info = {
			'width': css_width,
			'height': css_height,
			'physicalWidth': physical_width,
			'physicalHeight': physical_height,
			'screenWidth': screen_width,
			'screenHeight': screen_height,
			'devicePixelRatio': device_pixel_ratio
		}
		op('/').store(f'wob_screen_{slot}', screen_info)
		
		# Update sensor_table
		t = op('sensor_table')
		if t is not None:
			row = _find_row(t, slot)
			if row is not None:
				t[row, 'css_width'] = css_width
				t[row, 'css_height'] = css_height
				t[row, 'physical_width'] = physical_width
				t[row, 'physical_height'] = physical_height
				t[row, 'screen_width'] = screen_width
				t[row, 'screen_height'] = screen_height
				t[row, 'device_pixel_ratio'] = device_pixel_ratio
		
		print(f'[WOB] Screen info updated: slot {slot} -> CSS: {css_width}x{css_height}, Physical: {physical_width}x{physical_height}, Screen: {screen_width}x{screen_height} (DPR: {device_pixel_ratio})')
