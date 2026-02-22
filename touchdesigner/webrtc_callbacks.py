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
	"""When WebRTC connects, auto-set webrtc_audio_1 Connection and Track."""
	audio_chop = op('webrtc_audio_1')
	if audio_chop is None:
		return
	try:
		tracks = webrtcDAT.getTracks(connectionId, 'audio', 'remote')
		track_id = tracks[0] if tracks and len(tracks) > 0 else None
		for par_name in ('webrtcconnection', 'Webrtcconnection'):
			if hasattr(audio_chop.par, par_name):
				setattr(audio_chop.par, par_name, connectionId)
				break
		if track_id:
			for par_name in ('webrtctrack', 'Webrtctrack'):
				if hasattr(audio_chop.par, par_name):
					setattr(audio_chop.par, par_name, track_id)
					break
		print(f'[WOB WebRTC] webrtc_audio_1 auto-selected conn={connectionId} track={track_id}')
	except Exception as e:
		print(f'[WOB WebRTC] Auto-select audio failed: {e}')


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


def onConnectionStateChange(webrtcDAT, connectionId, state):
	"""Called when the overall connection state changes."""
	print(f'[WOB WebRTC] connectionId={connectionId} state={state}')
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
