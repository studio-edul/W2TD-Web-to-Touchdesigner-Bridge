import socket
import os
import subprocess
import sys
import platform

W2TD_BASE = 'W2TD'
W2TD_AUDIO = f'{W2TD_BASE}/webrtc_audio_container'


def _w2td_base():
	try:
		p = parent(1)
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
	return op(W2TD_BASE)


def _op(path_suffix, fallback_name=None):
	base = _w2td_base()
	if base:
		o = base.op(path_suffix)
		if o is not None:
			return o
	return op(fallback_name or path_suffix.split('/')[-1])


def get_local_ip():
	try:
		s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
		s.connect(('8.8.8.8', 80))
		ip = s.getsockname()[0]
		s.close()
		return ip
	except Exception as e:
		print(f'[W2TD Error] Failed to detect IP: {e}')
		return '127.0.0.1'

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
]
MAX_CLIENTS = 20

def _init_tables():
	t = _op('sensor_table')
	if t is not None:
		t.clear()
		t.appendRow(SENSOR_COLS)
		# No pre-populated rows — rows are added on connect, removed on disconnect
		print(f'[W2TD] sensor_table initialized (dynamic rows, max {MAX_CLIENTS} slots)')
	else:
		print('[W2TD Error] sensor_table DAT not found - create a Table DAT named "sensor_table"')

	tt = _op('touch_table')
	if tt is not None:
		tt.clear()
		tt.appendRow(['slot', 'touch_id', 'x', 'y', 'state'])
		print('[W2TD] touch_table initialized')
	else:
		print('[W2TD Error] touch_table DAT not found - create a Table DAT named "touch_table"')

	wt = _op('webrtc_audio_container/webrtc_table', 'webrtc_table')
	if wt is not None:
		wt.clear()
		wt.appendRow(['slot', 'name', 'conn_id', 'state'])
		print('[W2TD] webrtc_table initialized')
	else:
		print('[W2TD Error] webrtc_table DAT not found - create a Table DAT named "webrtc_table"')

def _init_webrtc_ice():
	"""Configure WebRTC DAT TURN servers if needed."""
	w = _op('webrtc_audio_container/webrtc_dat', 'webrtc_dat')
	if w is None:
		return
	# TURN servers can be added manually through TouchDesigner UI if needed.
	print('[W2TD] WebRTC DAT ICE initialization complete')


def _set_par(op_node, primary, value, fallbacks=()):
	"""Set an operator parameter by trying primary name then fallbacks."""
	for name in (primary,) + tuple(fallbacks):
		if hasattr(op_node.par, name):
			try:
				setattr(op_node.par, name, value)
				return True
			except Exception as e:
				print(f'[W2TD Error] _set_par {name}={value} failed: {e}')
	return False


def install_packages():
	"""Install required Python packages into TD's Python environment.
	This function is called automatically on onCreate, or can be called manually.
	"""
	PACKAGES = ['qrcode[pil]', 'pycloudflared']
	CERTIFI_PACKAGE = 'certifi'
	
	print('[W2TD Setup] Starting package installation...')
	print(f'[W2TD Setup] Python: {sys.executable}')
	print(f'[W2TD Setup] Platform: {platform.system()}')
	all_ok = True
	
	# CREATE_NO_WINDOW is Windows-only
	kwargs = {}
	if platform.system() == 'Windows':
		kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW
	
	# Install certifi first with --upgrade to fix SSL certificate issues (especially on macOS)
	print(f'[W2TD Setup] Installing {CERTIFI_PACKAGE} (SSL certificates)...')
	try:
		subprocess.check_call(
			[sys.executable, '-m', 'pip', 'install', '--upgrade', '--quiet', CERTIFI_PACKAGE],
			**kwargs
		)
		print(f'[W2TD Setup] {CERTIFI_PACKAGE} OK')
	except Exception as e:
		print(f'[W2TD Setup Error] {CERTIFI_PACKAGE} FAILED: {e}')
		all_ok = False
	
	# Install other packages
	for pkg in PACKAGES:
		print(f'[W2TD Setup] Installing {pkg}...')
		try:
			subprocess.check_call(
				[sys.executable, '-m', 'pip', 'install', '--quiet', pkg],
				**kwargs
			)
			print(f'[W2TD Setup] {pkg} OK')
		except Exception as e:
			print(f'[W2TD Setup Error] {pkg} FAILED: {e}')
			all_ok = False
	
	if all_ok:
		print('[W2TD Setup] All packages installed. You can now use W2TD from any directory.')
		print('[W2TD Setup] Note: Restart TouchDesigner if SSL certificate errors persist.')
	else:
		print('[W2TD Setup Error] Some packages failed. Check the log above.')


def onCreate():
	"""Called when Execute DAT is created. Install packages automatically."""
	print('[W2TD] onCreate triggered - installing packages...')
	install_packages()


def _configure_ssl():
	"""Configure SSL certificates (must run before any HTTPS/cloudflared operations)."""
	try:
		import certifi
		import ssl
		cert_path = certifi.where()
		os.environ['SSL_CERT_FILE'] = cert_path
		os.environ['REQUESTS_CA_BUNDLE'] = cert_path
		ssl._create_default_https_context = lambda: ssl.create_default_context(cafile=cert_path)
		print(f'[W2TD] SSL certificates configured: {cert_path}')
	except ImportError:
		print('[W2TD Error] certifi not installed. Run op("w2td_setup").module.install() first.')
	except Exception as e:
		print(f'[W2TD Error] SSL config warning: {e}')


def onStart():
	print('[W2TD] onStart triggered')
	_configure_ssl()
	_init_tables()
	_init_webrtc_ice()
	generate()

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

def generate():
	print('[W2TD] generate() start')

	# Read port from w2td_config (default: 9980)
	cfg = _read_config()
	port_val = cfg.get('Port') or cfg.get('port')
	try:
		port = int(port_val) if port_val else 9980
	except (ValueError, TypeError):
		port = 9980
	print(f'[W2TD] Using port: {port}')

	# 1. Import qrcode
	try:
		import qrcode
		print('[W2TD] qrcode import OK')
	except ImportError:
		print('[W2TD Error] qrcode not installed. Run op("w2td_setup").module.install() first.')
		return

	# 2. Cloudflare tunnel (for cross-network access) - required for mobile
	url = None
	last_error = None
	os.environ['TQDM_DISABLE'] = '1'
	os.environ['PYCLOUDFLARED_LINES_TO_CHECK'] = '100'
	try:
		import time
		from contextlib import redirect_stdout, redirect_stderr
		from pycloudflared import try_cloudflare
		print('[W2TD] Starting Cloudflare tunnel... (no signup required)')
		for attempt in range(3):
			try:
				with open(os.devnull, 'w') as devnull:
					with redirect_stdout(devnull), redirect_stderr(devnull):
						result = try_cloudflare(port=port, verbose=False)
				url = result.tunnel
				break
			except Exception as e:
				last_error = e
				if attempt < 2:
					print(f'[W2TD Error] Tunnel attempt {attempt + 1} failed: {e}')
					time.sleep(2)
				else:
					raise
		if url:
			print(f'[W2TD] Cloudflare URL: {url}')
	except ImportError:
		last_error = 'pycloudflared not installed'
		print('[W2TD Error] pycloudflared not installed.')
	except Exception as e:
		last_error = e

	if url is None:
		err_msg = str(last_error) if last_error else 'Unknown error'
		print(f'[W2TD Error] Cloudflare tunnel failed: {err_msg}')
		return

	op('/').store('w2td_url', url)

	host = url.replace('https://', '').replace('http://', '').strip()
	GITHUB_PAGES_URL = 'https://w2td-pro.studio-edul.com/'
	qr_url = GITHUB_PAGES_URL + '?td=' + host
	w2td = op('../W2TD') or _w2td_base()
	if w2td and hasattr(w2td.par, 'url'):
		try:
			w2td.par.url = qr_url
		except Exception as e:
			print(f'[W2TD Error] W2TD.par.url set failed: {e}')
	print(f'[W2TD] QR URL: {qr_url}')

	# 3. Generate QR code
	try:
		qr = qrcode.QRCode(box_size=10, border=4)
		qr.add_data(qr_url)
		qr.make(fit=True)
		img = qr.make_image(fill_color='black', back_color='white')
		print('[W2TD] QR image generated')
	except Exception as e:
		print(f'[W2TD Error] QR generation failed: {e}')
		return

	# 4. Save to file
	try:
		save_path = os.path.join(project.folder, 'qr.png')
		print(f'[W2TD] Save path: {save_path}')
		img.save(save_path)
		print(f'[W2TD] File saved: {os.path.exists(save_path)}')
	except Exception as e:
		print(f'[W2TD Error] File save failed: {e}')
		return

	# 5. Reload Movie File In TOP
	try:
		movie_top = _op('qr_movie_top')
		if movie_top is None:
			print('[W2TD Error] qr_movie_top not found - check node name')
			return
		print(f'[W2TD] qr_movie_top found: {movie_top}')
		movie_top.par.file = save_path
		movie_top.par.reloadpulse.pulse()
		print('[W2TD] TOP reloaded')
	except Exception as e:
		print(f'[W2TD Error] TOP reload failed: {e}')
		return

	# 6. Store base URL info for cam_render_sync.py to build slot Web Render TOP URLs.
	# Web Render TOPs are managed dynamically inside webrtc_video_container by cam_render_sync.py.
	try:
		tls_on = False
		web_srv = _op('web_server_dat')
		if web_srv is not None:
			for _par in ('secure', 'tls', 'https', 'usessl'):
				if bool(getattr(web_srv.par, _par, False)):
					tls_on = True
					break
		local_ip = get_local_ip()
		scheme = 'https' if tls_on else 'http'
		op('/').store('w2td_cam_base_url', f'{scheme}://{local_ip}:{port}')
		op('/').store('w2td_web_port', port)
		op('/').store('w2td_cam_tls', tls_on)
		print(f'[W2TD] cam base URL stored: {scheme}://{local_ip}:{port}')
		# Also set URL on legacy single web_render_top if it exists
		web_render = _op('web_render_top')
		if web_render is not None:
			receiver_url = f'{scheme}://{local_ip}:{port}/cam_receiver.html?port={port}'
			if tls_on:
				receiver_url += '&tls=1'
			web_render.par.url = receiver_url
			print(f'[W2TD] web_render_top URL set: {receiver_url}')
	except Exception as e:
		print(f'[W2TD Error] cam base URL store failed: {e}')

	print('[W2TD] generate() done')
