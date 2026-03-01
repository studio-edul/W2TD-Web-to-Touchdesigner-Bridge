"""
WOB WebRTC DAT Callbacks
========================
Set this file as the "Callbacks DAT" parameter of the WebRTC DAT named 'webrtc_dat'.

TD node setup required:
  - WebRTC DAT:        name = 'webrtc_dat', Callbacks DAT = 'webrtc_callbacks'
  - Video Stream In TOP: name = 'webrtc_video_1', Protocol = WebRTC, WebRTC DAT = 'webrtc_dat'
  - Audio Stream In CHOP: name = 'webrtc_audio_1', Protocol = WebRTC, WebRTC DAT = 'webrtc_dat'

connectionId = slot number as string (e.g. '1', '2', ...)
"""

import json


def _auto_select_audio_chop(webrtcDAT, connectionId):
	"""When WebRTC connects, auto-set webrtc_audio_1 Connection."""
	audio_chop = op('webrtc_audio_1')
	if audio_chop is None:
		print('[WOB WebRTC] webrtc_audio_1 NOT FOUND — create Audio Stream In CHOP named "webrtc_audio_1"')
		return
	# TD version differences: try all known Connection parameter names.
	# Note: getTracks() is not a valid TD Python API — connection-only is sufficient.
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
				print(f'[WOB WebRTC] Set {par_name} failed: {e}')
	if not set_ok:
		# Dump all par names containing webrtc/connect/track so we can find the correct one
		try:
			relevant = [p.name for p in audio_chop.pars()
			            if any(k in p.name.lower() for k in ('webrtc', 'connect', 'track', 'stream'))]
			print(f'[WOB WebRTC] webrtc_audio_1 relevant pars: {relevant}')
		except Exception:
			pass
	print(f'[WOB WebRTC] webrtc_audio_1 conn={connectionId!r} type={type(connectionId).__name__} par={matched_par} ok={set_ok}')


def _send_to_client(connectionId, data):
	"""Send a JSON message back to the mobile client via Web Server DAT."""
	ws_path = op('/').fetch('wob_webserver_op', '')
	ws = op(ws_path) if ws_path else None
	if ws is None:
		print(f'[WOB WebRTC] Web Server DAT not found (path: {ws_path})')
		return

	addr = op('/').fetch(f'wob_webrtc_addr_{connectionId}', None)
	if addr is None:
		print(f'[WOB WebRTC] No client addr for connectionId={connectionId}')
		return

	try:
		ws.webSocketSendText(addr, json.dumps(data))
	except Exception as e:
		print(f'[WOB WebRTC] Send failed for connectionId={connectionId}: {e}')


def onOffer(webrtcDAT, connectionId, localSdp):
	"""Called when TD creates a local offer (TD→browser direction, not used in browser→TD flow)."""
	webrtcDAT.setLocalDescription(connectionId, 'offer', localSdp, stereo=False)
	_send_to_client(connectionId, {'type': 'webrtc_offer', 'sdp': localSdp})


def onAnswer(webrtcDAT, connectionId, localSdp):
	"""Called after createAnswer() — set local description and send answer to browser."""
	webrtcDAT.setLocalDescription(connectionId, 'answer', localSdp, stereo=False)
	_send_to_client(connectionId, {'type': 'webrtc_answer', 'sdp': localSdp})
	print(f'[WOB WebRTC] Answer sent to connectionId={connectionId}')


def onIceCandidate(webrtcDAT, connectionId, candidate, lineIndex, sdpMid):
	"""Called when TD discovers an ICE candidate — forward to browser."""
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


def _wt_set_state(conn_id, state):
	"""Update state column in webrtc_table for the given conn_id."""
	t = op('webrtc_table')
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
	t = op('webrtc_table')
	if t is None:
		return
	for r in range(1, t.numRows):
		try:
			if str(t[r, 'conn_id']) == str(conn_id):
				t.deleteRow(r)
				return
		except Exception:
			pass

def onConnectionStateChange(webrtcDAT, connectionId, state):
	"""Called when the overall connection state changes."""
	print(f'[WOB WebRTC] connectionId={connectionId} state={state}')
	if state in ('failed', 'closed', 'disconnected'):
		_wt_remove(connectionId)
	else:
		_wt_set_state(connectionId, state)
	if state in ('failed', 'closed', 'disconnected'):
		# Notify client
		_send_to_client(connectionId, {
			'type': 'webrtc_state',
			'state': state,
		})
	elif state == 'connected':
		# Auto-select WebRTC Connection and Track in webrtc_audio_1
		_auto_select_audio_chop(webrtcDAT, connectionId)


def onIceConnectionStateChange(webrtcDAT, connectionId, state):
	"""Called when the ICE connection state changes."""
	print(f'[WOB WebRTC] ICE connectionId={connectionId} iceState={state}')
