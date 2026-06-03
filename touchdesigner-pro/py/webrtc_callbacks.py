"""
W2TD WebRTC DAT Callbacks
========================
Set this file as the "Callbacks DAT" parameter of the WebRTC DAT named 'webrtc_dat'.
Nodes are under W2TD_Pro/webrtc_audio_container (relative path).
"""

import json

W2TD_BASE = 'W2TD_Pro'
W2TD_AUDIO = f'{W2TD_BASE}/webrtc_audio_container'


def _w2td_base():
	try:
		p = parent(2)
		if p:
			return p
	except NameError:
		pass
	for p in ('project1', 'project'):
		w = op(f'{p}/{W2TD_BASE}')
		if w:
			return w
	root = op('/')
	if root and root.children:
		w = root.children[0].op(W2TD_BASE)
		if w:
			return w
	return op(W2TD_BASE) or op('W2TD')


def _op_web():
	base = _w2td_base()
	if base:
		w = base.op('web_server_dat')
		if w:
			return w
	return op('web_server_dat')


def _op_audio_chop(name):
	base = _w2td_base()
	if base:
		c = base.op('webrtc_audio_container')
		if c:
			chop = c.op(name)
			if chop:
				return chop
	return op(name)


def _op_webrtc_sync():
	base = _w2td_base()
	if base:
		for name in ('webrtc_auto_sync', 'webrtc_table_sync'):
			s = base.op(name)
			if s:
				return s
	return op('webrtc_auto_sync') or op('webrtc_table_sync')


def _auto_select_audio_chop(webrtcDAT, connectionId):
	"""When WebRTC connects, auto-set webrtc_audio_1 Connection."""
	audio_chop = _op_audio_chop('webrtc_audio_1')
	if audio_chop is None:
		print('[W2TD WebRTC Error] webrtc_audio_1 not found - create Audio Stream In CHOP named "webrtc_audio_1"')
		return
	# TD version differences: try all known Connection parameter names.
	# Note: getTracks() is not a valid TD Python API - connection-only is sufficient.
	CONN_PAR_NAMES = ('webrtcconnection', 'Webrtcconnection', 'connection', 'Connection')
	set_ok = False
	matched_par = None
	for par_name in CONN_PAR_NAMES:
		if hasattr(audio_chop.par, par_name):
			try:
				setattr(audio_chop.par, par_name, connectionId)
				set_ok = True
				matched_par = par_name
				break
			except Exception as e:
				print(f'[W2TD WebRTC Error] Set {par_name} failed: {e}')
	if not set_ok:
		# Dump all par names containing webrtc/connect/track so we can find the correct one
		try:
			relevant = [p.name for p in audio_chop.pars()
			            if any(k in p.name.lower() for k in ('webrtc', 'connect', 'track', 'stream'))]
			# print(f'[W2TD WebRTC] webrtc_audio_1 relevant pars: {relevant}')
		except Exception:
			pass
	# print(f'[W2TD WebRTC] webrtc_audio_1 conn={connectionId!r} type={type(connectionId).__name__} par={matched_par} ok={set_ok}')


def _send_to_client(connectionId, data):
	"""Send a JSON message back to the mobile client via Web Server DAT."""
	ws = _op_web()
	if ws is None:
		print('[W2TD WebRTC Error] Web Server DAT not found - create web_server_dat under W2TD_Pro')
		return

	addr = op('/').fetch(f'w2td_webrtc_addr_{connectionId}', None)
	if addr is None:
		print(f'[W2TD WebRTC Error] No client addr for connectionId={connectionId}')
		return

	try:
		ws.webSocketSendText(addr, json.dumps(data))
	except Exception as e:
		print(f'[W2TD WebRTC Error] Send failed for connectionId={connectionId}: {e}')


def onOffer(webrtcDAT, connectionId, localSdp):
	"""Called when TD creates a local offer (TD->browser direction, for renegotiation after addTrack)."""
	webrtcDAT.setLocalDescription(connectionId, 'offer', localSdp, stereo=False)
	_send_to_client(connectionId, {'type': 'webrtc_offer', 'sdp': localSdp})


def onAnswer(webrtcDAT, connectionId, localSdp):
	"""Called after createAnswer() - set local description and send answer to browser."""
	webrtcDAT.setLocalDescription(connectionId, 'answer', localSdp, stereo=False)
	_send_to_client(connectionId, {'type': 'webrtc_answer', 'sdp': localSdp})
	# print(f'[W2TD WebRTC] Answer sent to connectionId={connectionId}')


def onIceCandidate(webrtcDAT, connectionId, candidate, lineIndex, sdpMid):
	"""Called when TD discovers an ICE candidate - forward to browser."""
	if not candidate:
		# End-of-candidates signal
		_send_to_client(connectionId, {
			'type': 'webrtc_ice',
			'candidate': None,
		})
		return
	_send_to_client(connectionId, {
		'type': 'webrtc_ice',
		'candidate': candidate,
		'sdpMLineIndex': lineIndex,
		'sdpMid': sdpMid,
	})


def _wt_table():
	base = _w2td_base()
	if base:
		c = base.op('webrtc_audio_container')
		if c:
			t = c.op('webrtc_table')
			if t:
				return t
	return op('webrtc_table')

def _wt_set_state(conn_id, state):
	"""Update state column in webrtc_table for the given conn_id."""
	t = _wt_table()
	if t is None:
		return
	for r in range(1, t.numRows):
		try:
			if str(t[r, 'conn_id']) == str(conn_id):
				t[r, 'state'] = state
				return
		except Exception:
			pass


def _wt_remove(conn_id):
	"""Remove row from webrtc_table when WebRTC connection closes."""
	t = _wt_table()
	if t is None:
		return
	for r in range(1, t.numRows):
		try:
			if str(t[r, 'conn_id']) == str(conn_id):
				t.deleteRow(r)
				return
		except Exception:
			pass

def _wt_remove_by_slot(slot):
	"""Remove all webrtc_table rows for the given slot."""
	t = _wt_table()
	if t is None:
		return
	for r in reversed(range(1, t.numRows)):
		try:
			if int(t[r, 'slot']) == slot:
				t.deleteRow(r)
		except Exception:
			pass

def _slot_for_conn_id(conn_id):
	"""Find slot number for a given conn_id from stored mapping."""
	for slot in range(1, op('/').fetch('w2td_max_clients', 20) + 1):
		stored = op('/').fetch(f'w2td_webrtc_slot_to_uuid_{slot}', None)
		if stored is not None and str(stored) == str(conn_id):
			return slot
	return None


def _defer_wt_update(webrtcDAT, connectionId, state, slot):
	"""Defer webrtc_table updates to next frame to avoid cook dependency loops."""
	def _do():
		if state in ('failed', 'closed', 'disconnected'):
			_wt_remove(connectionId)
			if slot is not None:
				_wt_remove_by_slot(slot)
		else:
			_wt_set_state(connectionId, state)
		# Run sync and auto_select after delay
		sync_mod = _op_webrtc_sync()
		if sync_mod is not None and hasattr(sync_mod, 'module') and hasattr(sync_mod.module, 'sync'):
			try:
				sync_mod.module.sync()
			except Exception as e:
				# print(f'[W2TD WebRTC Error] webrtc_table_sync failed: {e}')
		if state == 'connected':
			_auto_select_audio_chop(webrtcDAT, connectionId)
			# Also auto-select TX track on Audio Stream Out CHOP (retry mechanism)
			_conn_id = connectionId
			_wrtcDAT = webrtcDAT
			_tx_attempt = [0]
			def _auto_select_tx():
				_tx_attempt[0] += 1
				for s in range(1, op('/').fetch('w2td_max_clients', 20) + 1):
					stored = op('/').fetch(f'w2td_webrtc_slot_to_uuid_{s}', None)
					if stored is not None and str(stored) == str(_conn_id):
						out_chop = _op_audio_chop(f'webrtc_audio_out_{s}')
						if out_chop is None:
							break
						track_name = f'audio_out_{s}'
						for par_name in ('webrtctrack', 'Webrtctrack', 'track', 'Track'):
							if hasattr(out_chop.par, par_name):
								p = getattr(out_chop.par, par_name)
								menus = getattr(p, 'menuNames', []) or []
								if track_name in menus:
									setattr(out_chop.par, par_name, track_name)
									# print(f'[W2TD WebRTC] Auto-selected TX track "{track_name}" on webrtc_audio_out_{s} (connected, attempt {_tx_attempt[0]})')
								elif menus:
									setattr(out_chop.par, par_name, menus[0])
									# print(f'[W2TD WebRTC] Auto-selected TX track "{menus[0]}" on webrtc_audio_out_{s} (connected, attempt {_tx_attempt[0]})')
								elif _tx_attempt[0] < 15:
									run(_auto_select_tx, delayFrames=5, fromOP=_wrtcDAT)
								break
						break
			run(_auto_select_tx, delayFrames=5, fromOP=webrtcDAT)

	run(_do, delayFrames=1, fromOP=webrtcDAT)


def onConnectionStateChange(webrtcDAT, connectionId, state):
	"""Called when the overall connection state changes."""
	# print(f'[W2TD WebRTC] connectionId={connectionId} state={state}')
	slot = _slot_for_conn_id(connectionId) if state in ('failed', 'closed', 'disconnected') else None
	# Defer webrtc_table update, sync, and auto_select to next frame -> avoids cook dependency loop
	_defer_wt_update(webrtcDAT, connectionId, state, slot)

	if state in ('failed', 'closed', 'disconnected'):
		# Notify client immediately (WebSocket is independent of cook)
		_send_to_client(connectionId, {
			'type': 'webrtc_state',
			'state': state,
		})


def onIceConnectionStateChange(webrtcDAT, connectionId, state):
	"""Called when the ICE connection state changes."""
	# print(f'[W2TD WebRTC] ICE connectionId={connectionId} iceState={state}')
