import json
import os
import time

W2TD_VERSION = '1.0.0'
GITHUB_PAGES_URL = 'https://w2td-dev.studio-edul.com/'
MAX_CLIENTS = 20
ACK_INTERVAL = 1.0  # seconds between data_ack signals per slot
STALE_TIMEOUT_DEFAULT = 30.0  # default seconds; overridden by w2td_config 'Disconnecttimeout'
STALE_CHECK_INTERVAL = 5.0    # min seconds between stale-slot scans (rate limit)

W2TD_BASE = 'W2TD'
W2TD_AUDIO = f'{W2TD_BASE}/webrtc_audio_container'


def _w2td_base():
	"""Get W2TD container: parent(1) when in Web Server DAT, or project/W2TD."""
	try:
		p = parent(1)
		if p:
			return p
	except NameError:
		pass
	for proj_name in ('project1', 'project'):
		w = op(f'{proj_name}/{W2TD_BASE}')
		if w:
			return w
	root = op('/')
	if root and root.children:
		w = root.children[0].op(W2TD_BASE)
		if w:
			return w
	return op(W2TD_BASE)


def _op(path_suffix, fallback_name=None):
	base = _w2td_base()
	if base:
		o = base.op(path_suffix)
		if o is not None:
			return o
	return op(fallback_name or path_suffix.split('/')[-1])

SENSOR_COLS = [
	'slot', 'connected', 'name',
	'ax', 'ay', 'az',
	'ga', 'gb', 'gg',
	'oa', 'ob', 'og',
	'lat', 'lon',
	'touch_count',
	'css_width', 'css_height',
	'physical_width', 'physical_height',
	'screen_width', 'screen_height',
	'device_pixel_ratio',
	'visibility',
]
WEBRTC_COLS = ['slot', 'name', 'conn_id', 'state']

# -- Persistent state (survives module reload via op('/').store/fetch) ----------
# These are stored in TD's global root op so module reloads don't reset them.

def _slots():
	"""Returns client_slots dict {addr: slot}."""
	return op('/').fetch('w2td_client_slots', {})

def _free():
	"""Returns free_slots list."""
	return op('/').fetch('w2td_free_slots', list(range(1, MAX_CLIENTS + 1)))

def _client_names():
	"""Returns client_names dict {slot: name}."""
	return op('/').fetch('w2td_client_names', {})

def _touch():
	"""Returns touch_count dict {slot: count}."""
	return op('/').fetch('w2td_touch_count', {})

def _save_slots(d):
	op('/').store('w2td_client_slots', d)

def _save_free(lst):
	op('/').store('w2td_free_slots', lst)

def _save_touch(d):
	op('/').store('w2td_touch_count', d)

def _save_client_names(d):
	op('/').store('w2td_client_names', d)

def _find_row(t, slot):
	"""Return the row index in sensor_table whose 'slot' column matches slot, or None."""
	for r in range(1, t.numRows):
		try:
			if int(t[r, 'slot']) == slot:
				return r
		except Exception:
			pass
	return None

def _wt_table():
	return _op('webrtc_audio_container/webrtc_table', 'webrtc_table')

def _wt_dat():
	return _op('webrtc_audio_container/webrtc_dat', 'webrtc_dat')

def _wt_find_row(t, conn_id):
	"""Find row in webrtc_table by conn_id."""
	for r in range(1, t.numRows):
		try:
			if str(t[r, 'conn_id']) == str(conn_id):
				return r
		except Exception:
			pass
	return None

def _wt_remove_by_slot(slot):
	"""Remove all webrtc_table rows for the given slot (e.g. before re-add on new offer)."""
	t = _wt_table()
	if t is None:
		return
	rows_to_del = []
	for r in range(1, t.numRows):
		try:
			if int(t[r, 'slot']) == slot:
				rows_to_del.append(r)
		except (ValueError, TypeError):
			pass
	for r in reversed(rows_to_del):
		t.deleteRow(r)

def _wt_add(slot, conn_id):
	"""Add row to webrtc_table when a WebRTC offer arrives."""
	t = _wt_table()
	if t is None:
		print('[W2TD Error] webrtc_table not found - create under W2TD/webrtc_audio_container')
		return
	_wt_remove_by_slot(slot)
	name = _client_names().get(slot, f'Slot {slot}')
	t.appendRow([slot, name, conn_id, 'connecting'])

def _wt_remove(conn_id):
	"""Remove row from webrtc_table when connection closes."""
	t = _wt_table()
	if t is None:
		return
	row = _wt_find_row(t, conn_id)
	if row is not None:
		t.deleteRow(row)

def _wt_update_name(slot, name):
	"""Update name for all webrtc_table rows matching slot."""
	t = _wt_table()
	if t is None:
		return
	for r in range(1, t.numRows):
		try:
			if int(t[r, 'slot']) == slot:
				t[r, 'name'] = name
		except Exception:
			pass

def _cam_receiver_addr(slot=None):
	"""Returns stored cam_receiver WebSocket address. If slot given, returns addr for that slot; else returns legacy single addr."""
	if slot is not None:
		return op('/').fetch(f'w2td_cam_receiver_addr_{slot}', None)
	return op('/').fetch('w2td_cam_receiver_addr', None)

def _save_cam_receiver_addr(addr, slot=None):
	if slot is not None:
		op('/').store(f'w2td_cam_receiver_addr_{slot}', addr)
	else:
		op('/').store('w2td_cam_receiver_addr', addr)

def _clear_cam_receiver_addr(addr):
	"""Clear cam_receiver addr(s) matching this addr (on disconnect)."""
	for s in range(1, MAX_CLIENTS + 1):
		if op('/').fetch(f'w2td_cam_receiver_addr_{s}', None) == addr:
			op('/').store(f'w2td_cam_receiver_addr_{s}', None)
	if op('/').fetch('w2td_cam_receiver_addr', None) == addr:
		op('/').store('w2td_cam_receiver_addr', None)

def _is_cam_receiver_addr(addr):
	"""True if addr is a registered cam_receiver."""
	for s in range(1, MAX_CLIENTS + 1):
		if op('/').fetch(f'w2td_cam_receiver_addr_{s}', None) == addr:
			return True
	return op('/').fetch('w2td_cam_receiver_addr', None) == addr

def _save_pending_cam_offer(slot, cam_type, sdp):
	"""Store pending cam offer to relay when cam_receiver connects later."""
	pending = op('/').fetch('w2td_pending_cam_offers', {})
	key = f'{slot}_{cam_type}'
	pending[key] = {'slot': slot, 'sdp': sdp, 'camType': cam_type}
	op('/').store('w2td_pending_cam_offers', pending)

def _save_pending_cam_ice(slot, cam_type, candidate_data):
	"""Accumulate pending ICE candidates to relay when cam_receiver connects later."""
	pending = op('/').fetch('w2td_pending_cam_ice', {})
	key = f'{slot}_{cam_type}'
	if key not in pending:
		pending[key] = []
	pending[key].append(candidate_data)
	op('/').store('w2td_pending_cam_ice', pending)

def _clear_pending_cam_for_slot(slot):
	"""Clear stored pending cam offers/ICE for a slot (e.g. on mobile disconnect)."""
	offers = op('/').fetch('w2td_pending_cam_offers', {})
	ice = op('/').fetch('w2td_pending_cam_ice', {})
	for cam_type in ('rear', 'front'):
		key = f'{slot}_{cam_type}'
		offers.pop(key, None)
		ice.pop(key, None)
	op('/').store('w2td_pending_cam_offers', offers)
	op('/').store('w2td_pending_cam_ice', ice)

def _addr_for_slot(slot):
	"""Return WebSocket addr for a given slot number, or None."""
	for addr, s in _slots().items():
		if s == slot:
			return addr
	return None

def _full_cleanup_slot(webServerDAT, addr, slot):
	"""onWebSocketClose와 동일한 정리 로직 — stale 슬롯 회수에도 사용.
	sensor_table, touch_table, webrtc 상태, pending cam, last_seen 모두 정리."""
	slots = _slots()
	slots.pop(addr, None)
	_save_slots(slots)

	free = _free()
	if slot not in free:
		free.append(slot)
		free.sort()
	_save_free(free)

	touch = _touch()
	touch.pop(slot, None)
	_save_touch(touch)

	t = _op('sensor_table')
	if t is not None:
		row = _find_row(t, slot)
		if row is not None:
			t.deleteRow(row)

	tt = _op('touch_table')
	if tt is not None:
		rows_to_delete = [r for r in range(1, tt.numRows) if int(tt[r, 'slot']) == slot]
		for r in reversed(rows_to_delete):
			tt.deleteRow(r)

	# WebRTC cleanup
	conn_id = op('/').fetch(f'w2td_webrtc_slot_to_uuid_{slot}', None)
	if conn_id:
		wrtc = _wt_dat()
		if wrtc is not None:
			try:
				wrtc.closeConnection(conn_id)
			except Exception:
				pass
		op('/').store(f'w2td_webrtc_addr_{conn_id}', None)
		op('/').store(f'w2td_webrtc_slot_to_uuid_{slot}', None)
	_wt_remove_by_slot(slot)
	_clear_pending_cam_for_slot(slot)

	op('/').store(f'w2td_last_seen_{slot}', 0)
	op('/').store(f'w2td_last_ack_{slot}', 0)


def cleanup_stale_slots(webServerDAT):
	"""마지막 메시지 후 Disconnecttimeout(config) 초 경과한 슬롯 강제 정리.
	모바일이 백그라운드 → 종료/네트워크 끊김 등 close 이벤트가 안 오는 모든 케이스 커버.
	(JS suspend되면 heartbeat ping도 멈추므로 같은 메커니즘으로 감지됨)

	자동 호출: onWebSocketReceiveText에서 STALE_CHECK_INTERVAL 마다 1회.
	수동 호출 (Timer CHOP 등): op('web_server_dat').module.cleanup_stale_slots(op('web_server_dat'))
	"""
	cfg = _read_config()
	try:
		timeout = float(cfg.get('Disconnecttimeout') or cfg.get('disconnecttimeout') or STALE_TIMEOUT_DEFAULT)
	except (ValueError, TypeError):
		timeout = STALE_TIMEOUT_DEFAULT

	now_t = time.time()
	stale = []
	for addr, slot in list(_slots().items()):
		last_seen = op('/').fetch(f'w2td_last_seen_{slot}', 0)
		if last_seen == 0:
			continue
		age = now_t - last_seen
		if age > timeout:
			stale.append((addr, slot, age))

	for addr, slot, age in stale:
		try:
			webServerDAT.webSocketClose(addr)
		except Exception:
			pass
		_full_cleanup_slot(webServerDAT, addr, slot)
		print(f'[W2TD] Stale slot {slot} released ({addr}) — no msg in {age:.0f}s (timeout={timeout:.0f}s)')

	return len(stale)


def _send_data_ack(webServerDAT, addr, slot):
	"""Send data_ack at most once per ACK_INTERVAL seconds per slot."""
	now = time.time()
	if now - op('/').fetch(f'w2td_last_ack_{slot}', 0) < ACK_INTERVAL:
		return
	op('/').store(f'w2td_last_ack_{slot}', now)
	try:
		webServerDAT.webSocketSendText(addr, json.dumps({'type': 'data_ack'}))
	except Exception:
		pass


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
	t = _op('sensor_table')
	if t is not None:
		row = _find_row(t, slot)
		if row is not None:
			t.deleteRow(row)
	op('/').store(f'w2td_last_seen_{slot}', 0)
	op('/').store(f'w2td_last_ack_{slot}', 0)

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
			print(f'[W2TD Cam Error] cam_answer: no mobile addr for slot {slot}')
			return
		cam_type = msg.get('camType', msg.get('cam_type', 'rear'))
		try:
			webServerDAT.webSocketSendText(mobile_addr, json.dumps({
				'type': 'webrtc_answer_cam',
				'sdp': sdp,
				'camType': cam_type,
			}))
			# print(f'[W2TD Cam] cam_answer relayed -> slot {slot} ({cam_type})')
		except Exception as e:
			print(f'[W2TD Cam Error] cam_answer relay error: {e}')

	elif msg_type == 'cam_ice':
		candidate = msg.get('candidate')
		slot = msg.get('slot')
		if not candidate or slot is None:
			return
		mobile_addr = _addr_for_slot(slot)
		if mobile_addr is None:
			return
		cam_type = msg.get('camType', msg.get('cam_type', 'rear'))
		try:
			webServerDAT.webSocketSendText(mobile_addr, json.dumps({
				'type': 'webrtc_ice_cam',
				'candidate': candidate,
				'sdpMLineIndex': msg.get('sdpMLineIndex', 0),
				'sdpMid': msg.get('sdpMid', ''),
				'camType': cam_type,
			}))
		except Exception as e:
			print(f'[W2TD Cam Error] cam_ice relay error: {e}')

	elif msg_type == 'cam_resolution':
		w = msg.get('width')
		h = msg.get('height')
		slot = msg.get('slot')
		if w is not None and h is not None and w > 0 and h > 0 and slot is not None:
			path = op('/').fetch(f'w2td_web_render_slot_{slot}', None)
			if path:
				top = op(path)
				if top:
					try:
						_dim_map = {'non-commercial': 1280, 'fhd': 1920}
						cfg = _read_config()
						res_key = 'non-commercial'
						for _k, _v in cfg.items():
							if _k.lower() == 'resolution':
								res_key = _v.strip().lower()
								break
						sq = _dim_map.get(res_key, 1280)
						top.par.outputresolution = 'custom'
						top.par.resolutionw = sq
						top.par.resolutionh = sq
						logged = op('/').fetch(f'w2td_cam_res_logged_{slot}', False)
						if not logged:
							# print(f'[W2TD Cam] web_render_top (slot {slot}) -> {sq}x{sq} ({res_key}), source: {int(w)}x{int(h)}')
							op('/').store(f'w2td_cam_res_logged_{slot}', True)
					except Exception as e:
						print(f'[W2TD Cam Error] Resolution set failed for slot {slot}: {e}')
				else:
					print(f'[W2TD Cam Error] web_render_top for slot {slot} not found')
			else:
				# print(f'[W2TD Cam] Received video resolution: {int(w)}x{int(h)} (slot {slot}, web_render not yet synced)')

# ------------------------------------------------------------------------------

def _read_config():
	"""Read settings from w2td_config Table DAT (key | value)."""
	cfg = _op('w2td_config')
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
	val = cfg.get('Maxclients') or cfg.get('maxclients') or cfg.get('max_clients')
	if val:
		try:
			MAX_CLIENTS = max(1, int(val))
		except ValueError:
			pass

	# Reset persistent state
	_save_slots({})
	_save_free(list(range(1, MAX_CLIENTS + 1)))
	_save_touch({})
	op('/').store('w2td_pending_cam_offers', {})
	op('/').store('w2td_pending_cam_ice', {})

	t = _op('sensor_table')
	if t is not None:
		t.clear()
		t.appendRow(SENSOR_COLS)
		# print(f'[W2TD] sensor_table initialized (dynamic rows, max {MAX_CLIENTS} slots)')
	else:
		print('[W2TD Error] sensor_table DAT not found - create a Table DAT named "sensor_table"')

	tt = _op('touch_table')
	if tt is not None:
		tt.clear()
		tt.appendRow(['slot', 'touch_id', 'x', 'y', 'state'])
		# print('[W2TD] touch_table initialized')
	else:
		print('[W2TD Error] touch_table DAT not found - create a Table DAT named "touch_table"')

	wt = _wt_table()
	if wt is not None:
		wt.clear()
		wt.appendRow(WEBRTC_COLS)
		# print('[W2TD] webrtc_table initialized')
	else:
		print('[W2TD Error] webrtc_table DAT not found - create a Table DAT named "webrtc_table"')


def _config_val(cfg, *keys, default=0):
	"""Try config keys in order; normalize to int."""
	for k in keys:
		if k in cfg:
			try:
				return int(float(cfg[k]))
			except (ValueError, TypeError):
				return default
	return default


def _config_msg(cfg):
	"""Build config JSON dict from w2td_config (Samplerate, Wakelock, Motion, Geolocation, ...)."""
	out = {
		'type':               'config',
		'sample_rate':        _config_val(cfg, 'Samplerate', default=30),
		'wake_lock':          _config_val(cfg, 'Wakelock', default=1),
		'sensor_motion':      _config_val(cfg, 'Motion', default=1),
		'sensor_orientation': _config_val(cfg, 'Orientation', default=1),
		'sensor_geolocation': _config_val(cfg, 'Geolocation', default=1),
		'sensor_touch':       _config_val(cfg, 'Touch', default=1),
		'dev_mode':           _config_val(cfg, 'Devmode', default=1),
		'sensor_rear_camera': _config_val(cfg, 'Rearcamera', default=0),
		'sensor_front_camera': _config_val(cfg, 'Frontcamera', default=0),
		'sensor_microphone':  _config_val(cfg, 'Microphone', default=1),
		'audio_echo_cancellation': _config_val(cfg, 'Echocancellation', default=0),
		'audio_noise_suppression': _config_val(cfg, 'Noisesuppression', default=0),
		'audio_auto_gain':    _config_val(cfg, 'Audiogain', default=0),
		'show_dots':          _config_val(cfg, 'Showdots', default=1),
	}
	ice_srv = cfg.get('Iceservers', '').strip()
	turn_srv = cfg.get('Turnserver', '').strip()
	if turn_srv or ice_srv:
		servers = []
		if ice_srv:
			try:
				servers = json.loads(ice_srv)
			except Exception:
				pass
		if not servers:
			servers = [
				{'urls': 'stun:stun.l.google.com:19302'},
				{'urls': 'stun:stun1.l.google.com:19302'}
			]
		if turn_srv:
			turn_user = cfg.get('Turnusername', '').strip()
			turn_pass = cfg.get('Turnpassword', '').strip()
			servers.append({
				'urls': turn_srv,
				'username': turn_user,
				'credential': turn_pass
			})
		out['ice_servers'] = servers

	if cfg.get('Icetransportpolicy', '').strip() == 'relay':
		out['ice_transport_policy'] = 'relay'
	return out


def broadcast_config(webServerDAT):
	"""Push updated config to all connected clients.
	Call from TD script after editing w2td_config:
	    op('web_server_dat').module.broadcast_config(op('web_server_dat'))
	w2td_config keys: sample_rate, wake_lock, sensors, dev_mode, camera, microphone
	"""
	cfg = _read_config()
	msg = json.dumps(_config_msg(cfg))
	for addr in list(_slots().keys()):
		try:
			webServerDAT.webSocketSendText(addr, msg)
		except Exception:
			pass
	# print(f'[W2TD] Config broadcast -> {len(_slots())} clients')
	
	try:
		_op('w2td_init').module._init_webrtc_ice()
	except Exception as e:
		# print(f'[W2TD Error] Failed to update WebRTC ICE on config broadcast: {e}')


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
	"""Serve cam_receiver.html locally; redirect all other requests to GitHub Pages."""
	uri = request.get('uri', '/')

	# Serve cam_receiver.html for Web Render TOP (served from Text DAT - no external file needed)
	if uri.startswith('/cam_receiver.html'):
		dat = _op('cam_receiver_html')
		if dat is not None:
			response['statusCode'] = 200
			response['statusReason'] = 'OK'
			response['headers'] = {'Content-Type': 'text/html; charset=utf-8'}
			response['data'] = dat.text
		else:
			response['statusCode'] = 404
			response['statusReason'] = 'Not Found'
			response['data'] = '<html><body>cam_receiver_html DAT not found in W2TD</body></html>'
			print('[W2TD Error] cam_receiver_html Text DAT not found - create a Text DAT named "cam_receiver_html" inside W2TD')
		return response

	stored_url = op('/').fetch('w2td_url', '')
	host = stored_url.replace('https://', '').replace('http://', '').strip()
	if not host:
		host = request.get('headers', {}).get('Host', '')
	short_host = host.replace('.trycloudflare.com', '') if host.endswith('.trycloudflare.com') else host
	# print(f'[W2TD] HTTP request -> host: {short_host}')
	redirect_url = GITHUB_PAGES_URL + ('?td=' + short_host if short_host else '')

	response['statusCode'] = 200
	response['statusReason'] = 'OK'
	response['data'] = f'''<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>W2TD</title>
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
  <h1>&#10003; W2TD</h1>
  <p>Redirecting...</p>
  <p><a href="{redirect_url}">Tap here if not redirected</a></p>
</body>
</html>'''
	return response


def onWebSocketOpen(webServerDAT, client):
	"""Accept connection only. Slot assignment is deferred to the first message (after identifying cam_receiver)."""
	try:
		addr = str(client)
		# cam_receiver is identified by hello message -> no slot assigned. Regular mobile gets slot on first message.
		pass
	except Exception as e:
		print(f'[W2TD Error] onWebSocketOpen: {e}')


def onWebSocketClose(webServerDAT, client):
	addr = str(client)

	# cam_receiver disconnect
	if _is_cam_receiver_addr(addr):
		_clear_cam_receiver_addr(addr)
		# print(f'[W2TD Cam] cam_receiver disconnected: {addr}')
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

	t = _op('sensor_table')
	if t is not None:
		row = _find_row(t, slot)
		if row is not None:
			t.deleteRow(row)

	tt = _op('touch_table')
	if tt is not None:
		rows_to_delete = [
			r for r in range(1, tt.numRows)
			if int(tt[r, 'slot']) == slot
		]
		for r in reversed(rows_to_delete):
			tt.deleteRow(r)

	# Clean up WebRTC state for this slot
	conn_id = op('/').fetch(f'w2td_webrtc_slot_to_uuid_{slot}', None)
	if conn_id:
		wrtc = _wt_dat()
		if wrtc is not None:
			try:
				wrtc.closeConnection(conn_id)
			except Exception:
				pass
		op('/').store(f'w2td_webrtc_addr_{conn_id}', None)
		op('/').store(f'w2td_webrtc_slot_to_uuid_{slot}', None)
	# Clean up webrtc_table by slot (works even without conn_id)
	_wt_remove_by_slot(slot)
	# Clear pending cam offers/ICE for this slot
	_clear_pending_cam_for_slot(slot)

	# On disconnect: clean up web_render_top nodes via cam_render_sync
	try:
		sync_op = _op('webrtc_video_container/cam_render_sync') or op('cam_render_sync')
		if sync_op and hasattr(sync_op, 'module') and hasattr(sync_op.module, 'sync'):
			sync_op.module.sync(table_dat=t)
		# Broadcast cam_receiver_ready to remaining clients -> triggers video re-send to reconnected TOP
		for mobile_addr in list(slots.keys()):
			try:
				webServerDAT.webSocketSendText(mobile_addr, json.dumps({'type': 'cam_receiver_ready'}))
			except Exception:
				pass
		if slots:
			# print(f'[W2TD Cam] cam_receiver_ready broadcast -> {len(slots)} remaining clients (after disconnect)')
	except Exception:
		pass

	print(f'[W2TD] Disconnected -> slot {slot} | {addr} | {len(slots)}/{MAX_CLIENTS} active')


def onWebSocketReceiveText(webServerDAT, client, data):
	addr = str(client)

	# Stale 슬롯 정리 (rate-limited) — 백그라운드 종료된 좀비 슬롯 회수
	now_t = time.time()
	last_check = op('/').fetch('w2td_last_stale_check', 0)
	if now_t - last_check > STALE_CHECK_INTERVAL:
		op('/').store('w2td_last_stale_check', now_t)
		try:
			cleanup_stale_slots(webServerDAT)
		except Exception as e:
			print(f'[W2TD Error] cleanup_stale_slots: {e}')

	# cam_receiver.html messages are routed separately (no slot)
	if _is_cam_receiver_addr(addr):
		try:
			msg = json.loads(data)
		except Exception:
			return
		_handle_cam_receiver_msg(webServerDAT, addr, msg)
		return

	try:
		msg = json.loads(data)
	except Exception:
		return
	# hello+cam_receiver: skip slot/table assignment -> prevents unnecessary web_render_top create/destroy (ERR_ABORTED)
	if msg.get('type') == 'hello' and msg.get('role') == 'cam_receiver':
		cr_slot = msg.get('slot')
		if cr_slot is not None and isinstance(cr_slot, (int, float)):
			cr_slot = int(cr_slot)
		if cr_slot is not None and 1 <= cr_slot <= MAX_CLIENTS:
			_save_cam_receiver_addr(addr, cr_slot)
		else:
			_save_cam_receiver_addr(addr)
		# print(f'[W2TD Cam] cam_receiver registered: {addr}' + (f' (slot {cr_slot})' if cr_slot else ''))
		# Replay pending cam offers/ICE
		pending_offers = op('/').fetch('w2td_pending_cam_offers', {})
		pending_ice = op('/').fetch('w2td_pending_cam_ice', {})
		sent_keys = []
		if pending_offers and cr_slot is not None:
			for key, offer in list(pending_offers.items()):
				if offer.get('slot') != cr_slot:
					continue
				try:
					webServerDAT.webSocketSendText(addr, json.dumps({
						'type': 'cam_offer', 'slot': offer['slot'], 'sdp': offer['sdp'], 'camType': offer['camType'],
					}))
					# print(f'[W2TD Cam] Replayed pending offer -> slot {offer["slot"]} ({offer["camType"]})')
					sent_keys.append(key)
				except Exception as e:
					print(f'[W2TD Cam Error] Pending offer replay error: {e}')
				for ice in pending_ice.get(key, []):
					try:
						webServerDAT.webSocketSendText(addr, json.dumps({
							'type': 'cam_ice', 'slot': ice['slot'], 'candidate': ice['candidate'],
							'sdpMLineIndex': ice.get('sdpMLineIndex', 0), 'sdpMid': ice.get('sdpMid', ''),
							'camType': ice['camType'],
						}))
					except Exception:
						pass
			for k in sent_keys:
				pending_offers.pop(k, None)
				pending_ice.pop(k, None)
			op('/').store('w2td_pending_cam_offers', pending_offers)
			op('/').store('w2td_pending_cam_ice', pending_ice)
		for mobile_addr in list(_slots().keys()):
			try:
				webServerDAT.webSocketSendText(mobile_addr, json.dumps({'type': 'cam_receiver_ready'}))
			except Exception:
				pass
		# print(f'[W2TD Cam] cam_receiver_ready broadcast -> {len(_slots())} clients')
		# Send current config to newly connected cam_receiver so it knows resolution immediately
		try:
			cfg = _read_config()
			config_msg = json.dumps(_config_msg(cfg))
			webServerDAT.webSocketSendText(addr, config_msg)
		except Exception as e:
			print(f'[W2TD Cam Error] config send to cam_receiver failed: {e}')
		return

	slots = _slots()
	slot = slots.get(addr)

	if slot is None:
		free = _free()
		if not free:
			try:
				webServerDAT.webSocketSendText(client, json.dumps({
					'type': 'rejected',
					'reason': f'Server is currently full ({MAX_CLIENTS} devices connected). Please try again in a moment.',
				}))
			except Exception:
				pass
			return
		slot = free.pop(0)
		slots[addr] = slot
		_save_slots(slots)
		_save_free(free)
		t2 = _op('sensor_table')
		if t2 is not None and _find_row(t2, slot) is None:
			names = _client_names()
			client_name = names.get(slot, f'Slot {slot}')
			row_vals = [slot, 1, client_name] + [0.0] * (len(SENSOR_COLS) - 3)
			row_vals[SENSOR_COLS.index('visibility')] = 1
			t2.appendRow(row_vals)
		print(f'[W2TD] Connected -> slot {slot} | {addr} | {len(slots)}/{MAX_CLIENTS} active')
		op('/').store(f'w2td_last_seen_{slot}', time.time())
		try:
			webServerDAT.webSocketSendText(client, json.dumps({'type': 'ack', 'slot': slot, 'td_version': W2TD_VERSION}))
		except Exception:
			pass
		cfg = _read_config()
		try:
			webServerDAT.webSocketSendText(client, json.dumps(_config_msg(cfg)))
		except Exception:
			pass

	op('/').store(f'w2td_last_seen_{slot}', time.time())

	msg_type = msg.get('type')

	if msg_type == 'sensor':
		t = _op('sensor_table')
		if t is None:
			return
		row = _find_row(t, slot)
		if row is None:
			return
		g = msg.get
		# Get client name
		names = _client_names()
		client_name = names.get(slot, f'Slot {slot}')
		
		# Get screen resolution (stored separately)
		screen_info = op('/').fetch(f'w2td_screen_{slot}', {})
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
			css_width, css_height,
			physical_width, physical_height,
			screen_width, screen_height,
			device_pixel_ratio,
		])
		# Send ack signal to indicate data received (rate-limited to 1/sec)
		_send_data_ack(webServerDAT, addr, slot)

	elif msg_type == 'touch':
		count = msg.get('count', 0)
		touch = _touch()
		touch[slot] = count
		_save_touch(touch)

		t = _op('sensor_table')
		if t is not None:
			row = _find_row(t, slot)
			if row is not None:
				t[row, 'touch_count'] = count

		tt = _op('touch_table')
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
		# Send ack signal for touch data (rate-limited to 1/sec)
		_send_data_ack(webServerDAT, addr, slot)

	elif msg_type == 'hello':
		# print(f'[W2TD] Hello from slot {slot} - OK')

	elif msg_type == 'webrtc_offer':
		sdp = msg.get('sdp')
		if not sdp:
			return
		wrtc = _wt_dat()
		if wrtc is None:
			print('[W2TD Error] webrtc_dat not found - create WebRTC DAT under W2TD/webrtc_audio_container')
			return
		old_conn = op('/').fetch(f'w2td_webrtc_slot_to_uuid_{slot}', None)
		if old_conn:
			try:
				wrtc.closeConnection(old_conn)
			except Exception:
				pass
			op('/').store(f'w2td_webrtc_addr_{old_conn}', None)
			_wt_remove(old_conn)
		try:
			conn_id = wrtc.openConnection()
			op('/').store(f'w2td_webrtc_addr_{conn_id}', addr)
			op('/').store(f'w2td_webrtc_slot_to_uuid_{slot}', conn_id)
			wrtc.setRemoteDescription(conn_id, 'offer', sdp)
			wrtc.createAnswer(conn_id)
			_wt_add(slot, conn_id)
			# print(f'[W2TD WebRTC] Offer received from slot {slot}, conn_id={conn_id}, creating answer...')
		except Exception as e:
			print(f'[W2TD WebRTC Error] Offer handling error: {e}')

	elif msg_type == 'webrtc_ice':
		candidate = msg.get('candidate')
		if not candidate:
			return
		wrtc = _wt_dat()
		if wrtc is None:
			return
		conn_id = op('/').fetch(f'w2td_webrtc_slot_to_uuid_{slot}', None)
		if conn_id is None:
			return
		line_index = int(msg.get('sdpMLineIndex', 0))
		sdp_mid = msg.get('sdpMid', '')
		try:
			wrtc.addIceCandidate(conn_id, candidate, line_index, sdp_mid)
		except Exception as e:
			print(f'[W2TD WebRTC Error] addIceCandidate error: {e}')

	elif msg_type == 'webrtc_offer_cam':
		# Camera offer from mobile -> relay to slot's cam_receiver as cam_offer
		sdp = msg.get('sdp')
		if not sdp:
			return
		cam_type = msg.get('camType', msg.get('cam_type', 'rear'))
		receiver_addr = _cam_receiver_addr(slot) or _cam_receiver_addr()
		if receiver_addr is None:
			# cam_receiver not yet open - store offer for replay when it connects
			_save_pending_cam_offer(slot, cam_type, sdp)
			# print(f'[W2TD Cam] cam_receiver not connected - offer stored (slot {slot}, {cam_type})')
			return
		# Clear stale pending for this slot before relaying fresh offer
		_clear_pending_cam_for_slot(slot)
		try:
			webServerDAT.webSocketSendText(receiver_addr, json.dumps({
				'type': 'cam_offer',
				'slot': slot,
				'sdp': sdp,
				'camType': cam_type,
			}))
			# print(f'[W2TD Cam] cam_offer relayed to receiver (slot {slot}, {cam_type})')
		except Exception as e:
			print(f'[W2TD Cam Error] cam_offer relay error: {e}')

	elif msg_type == 'webrtc_ice_cam':
		# ICE from mobile -> relay to slot's cam_receiver
		candidate = msg.get('candidate')
		if not candidate:
			return
		cam_type = msg.get('camType', msg.get('cam_type', 'rear'))
		receiver_addr = _cam_receiver_addr(slot) or _cam_receiver_addr()
		if receiver_addr is None:
			# cam_receiver not connected - store ICE for replay
			_save_pending_cam_ice(slot, cam_type, {
				'slot': slot,
				'candidate': candidate,
				'sdpMLineIndex': msg.get('sdpMLineIndex', 0),
				'sdpMid': msg.get('sdpMid', ''),
				'camType': cam_type,
			})
			return
		try:
			webServerDAT.webSocketSendText(receiver_addr, json.dumps({
				'type': 'cam_ice',
				'slot': slot,
				'candidate': candidate,
				'sdpMLineIndex': msg.get('sdpMLineIndex', 0),
				'sdpMid': msg.get('sdpMid', ''),
				'camType': cam_type,
			}))
		except Exception as e:
			print(f'[W2TD Cam Error] webrtc_ice_cam relay error: {e}')

	elif msg_type == 'ping':
		# Heartbeat ping from mobile -> respond with pong
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
		t = _op('sensor_table')
		if t is not None:
			row = _find_row(t, slot)
			if row is not None:
				t[row, 'name'] = client_name
		
		_wt_update_name(slot, client_name)
		# print(f'[W2TD] Client name updated: slot {slot} -> {client_name}')

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
		op('/').store(f'w2td_screen_{slot}', screen_info)
		
		# Update sensor_table
		t = _op('sensor_table')
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
		
		# print(f'[W2TD] Screen info: slot {slot} | CSS {css_width}x{css_height} / Physical {physical_width}x{physical_height} (DPR {device_pixel_ratio})')

	elif msg_type == 'visibility':
		state = msg.get('state')
		if state == 'hidden':
			t = _op('sensor_table')
			if t is not None:
				row = _find_row(t, slot)
				if row is not None:
					for col in ('ax', 'ay', 'az', 'ga', 'gb', 'gg', 'oa', 'ob', 'og', 'lat', 'lon', 'touch_count'):
						try:
							t[row, col] = 0
						except Exception:
							pass
					try:
						t[row, 'visibility'] = 0
					except Exception:
						pass
			tt = _op('touch_table')
			if tt is not None:
				rows_to_delete = [r for r in range(1, tt.numRows) if int(tt[r, 'slot']) == slot]
				for r in reversed(rows_to_delete):
					tt.deleteRow(r)
			touch = _touch()
			touch[slot] = 0
			_save_touch(touch)
			# print(f'[W2TD] Slot {slot} backgrounded — sensor values zeroed')
		elif state == 'visible':
			t = _op('sensor_table')
			if t is not None:
				row = _find_row(t, slot)
				if row is not None:
					try:
						t[row, 'visibility'] = 1
					except Exception:
						pass
			# print(f'[W2TD] Slot {slot} foregrounded — resuming')

