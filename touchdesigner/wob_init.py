import socket
import os
import subprocess

def get_local_ip():
	try:
		s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
		s.connect(('8.8.8.8', 80))
		ip = s.getsockname()[0]
		s.close()
		return ip
	except Exception as e:
		print(f'[WOB] Failed to detect IP: {e}')
		return '127.0.0.1'

SENSOR_COLS = [
	'slot', 'connected',
	'ax', 'ay', 'az',
	'ga', 'gb', 'gg',
	'oa', 'ob', 'og',
	'lat', 'lon',
	'touch_count',
	'trig',
]
MAX_CLIENTS = 20

def _init_tables():
	t = op('sensor_table')
	if t is not None:
		t.clear()
		t.appendRow(SENSOR_COLS)
		# No pre-populated rows — rows are added on connect, removed on disconnect
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

def _init_webrtc_ice():
	"""Configure WebRTC DAT TURN servers for cross-network (tunnel/cloudflared)."""
	try:
		w = op('webrtc_dat')
		if w is None:
			return
		w.par.turn0server = 'turn:openrelay.metered.ca:80'
		w.par.username = 'openrelayproject'
		w.par.password = 'openrelayproject'
		# turn1server if available
		if hasattr(w.par, 'turn1server'):
			w.par.turn1server = 'turn:openrelay.metered.ca:443'
		print('[WOB] WebRTC DAT TURN configured for cross-network')
	except Exception as e:
		print(f'[WOB] WebRTC ICE init skip: {e}')


def onStart():
	print('[WOB] onStart triggered')
	_init_tables()
	_init_webrtc_ice()
	generate()

def generate():
	print('[WOB] generate() start')

	# 1. Import qrcode
	try:
		import qrcode
		print('[WOB] qrcode import OK')
	except ImportError:
		print('[WOB] qrcode not installed. Run op("wob_setup").module.install() first.')
		return

	# 2. Start Cloudflare tunnel
	url = None
	try:
		from pycloudflared import try_cloudflare
		print('[WOB] Starting Cloudflare tunnel... (no signup required)')
		result = try_cloudflare(port=9980)
		url = result.tunnel  # e.g. "https://xxxx.trycloudflare.com"
		print(f'[WOB] Cloudflare URL: {url}')
	except ImportError:
		print('[WOB] pycloudflared not installed. Run op("wob_setup").module.install() first.')
	except Exception as e:
		print(f'[WOB] Cloudflare tunnel failed: {e} — falling back to local HTTPS')

	if url is None:
		ip = get_local_ip()
		url = f'https://{ip}:9980'
		print(f'[WOB] Local URL: {url}')

	op('/').store('wob_url', url)  # Store URL internally for callbacks.py

	# Build QR URL: point directly to GitHub Pages with ?td= param
	host = url.replace('https://', '').replace('http://', '').strip()
	GITHUB_PAGES_URL = 'https://studio-edul.github.io/Web-Osc-Bridge/'
	qr_url = GITHUB_PAGES_URL + '?td=' + host
	op('wob_url_text').par.text = qr_url
	print(f'[WOB] QR URL: {qr_url}')

	# 3. Generate QR code
	try:
		qr = qrcode.QRCode(box_size=10, border=4)
		qr.add_data(qr_url)
		qr.make(fit=True)
		img = qr.make_image(fill_color='black', back_color='white')
		print('[WOB] QR image generated')
	except Exception as e:
		print(f'[WOB] QR generation failed: {e}')
		return

	# 4. Save to file
	try:
		save_path = os.path.join(project.folder, 'qr.png')
		print(f'[WOB] Save path: {save_path}')
		img.save(save_path)
		print(f'[WOB] File saved: {os.path.exists(save_path)}')
	except Exception as e:
		print(f'[WOB] File save failed: {e}')
		return

	# 5. Reload Movie File In TOP
	try:
		movie_top = op('qr_movie_top')
		if movie_top is None:
			print('[WOB] qr_movie_top not found - check node name')
			return
		print(f'[WOB] qr_movie_top found: {movie_top}')
		movie_top.par.file = save_path
		movie_top.par.reloadpulse.pulse()
		print('[WOB] TOP reloaded')
	except Exception as e:
		print(f'[WOB] TOP reload failed: {e}')
		return

	print('[WOB] generate() done')
