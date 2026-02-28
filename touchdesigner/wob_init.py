import socket
import os
import subprocess
import sys
import platform

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
		# freeTURN (free, no signup required)
		w.par.turn0server = 'turn:freeturn.net:3478'
		w.par.username = 'free'
		w.par.password = 'free'
		if hasattr(w.par, 'turn1server'):
			w.par.turn1server = 'turns:freeturn.net:5349'
		print('[WOB] WebRTC DAT TURN configured for cross-network')
	except Exception as e:
		print(f'[WOB] WebRTC ICE init skip: {e}')


def install_packages():
	"""Install required Python packages into TD's Python environment.
	This function is called automatically on onCreate, or can be called manually.
	"""
	PACKAGES = ['qrcode[pil]', 'pycloudflared']
	CERTIFI_PACKAGE = 'certifi'
	
	print('[WOB Setup] Starting package installation...')
	print(f'[WOB Setup] Python: {sys.executable}')
	print(f'[WOB Setup] Platform: {platform.system()}')
	all_ok = True
	
	# CREATE_NO_WINDOW is Windows-only
	kwargs = {}
	if platform.system() == 'Windows':
		kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW
	
	# Install certifi first with --upgrade to fix SSL certificate issues (especially on macOS)
	print(f'[WOB Setup] Installing {CERTIFI_PACKAGE} (SSL certificates)...')
	try:
		subprocess.check_call(
			[sys.executable, '-m', 'pip', 'install', '--upgrade', '--quiet', CERTIFI_PACKAGE],
			**kwargs
		)
		print(f'[WOB Setup] {CERTIFI_PACKAGE} OK')
	except Exception as e:
		print(f'[WOB Setup] {CERTIFI_PACKAGE} FAILED: {e}')
		all_ok = False
	
	# Install other packages
	for pkg in PACKAGES:
		print(f'[WOB Setup] Installing {pkg}...')
		try:
			subprocess.check_call(
				[sys.executable, '-m', 'pip', 'install', '--quiet', pkg],
				**kwargs
			)
			print(f'[WOB Setup] {pkg} OK')
		except Exception as e:
			print(f'[WOB Setup] {pkg} FAILED: {e}')
			all_ok = False
	
	if all_ok:
		print('[WOB Setup] All packages installed. You can now use WOB from any directory.')
		print('[WOB Setup] Note: Restart TouchDesigner if SSL certificate errors persist.')
	else:
		print('[WOB Setup] Some packages failed. Check the log above.')


def onCreate():
	"""Called when Execute DAT is created. Install packages automatically."""
	print('[WOB] onCreate triggered - installing packages...')
	install_packages()


def onStart():
	print('[WOB] onStart triggered')
	_init_tables()
	_init_webrtc_ice()
	generate()

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

def generate():
	print('[WOB] generate() start')

	# Read port from wob_config (default: 9980)
	cfg = _read_config()
	try:
		port = int(cfg.get('port', 9980))
	except (ValueError, TypeError):
		port = 9980
	print(f'[WOB] Using port: {port}')

	# SSL certificate configuration (using certifi) - fixes macOS SSL issues
	try:
		import certifi
		import ssl
		# Set certifi certificate bundle path as environment variables
		cert_path = certifi.where()
		os.environ['SSL_CERT_FILE'] = cert_path
		os.environ['REQUESTS_CA_BUNDLE'] = cert_path
		# Configure default SSL context to use certifi (wrapped as function)
		def _create_default_context():
			return ssl.create_default_context(cafile=cert_path)
		ssl._create_default_https_context = _create_default_context
		print(f'[WOB] SSL certificates configured: {cert_path}')
	except ImportError:
		print('[WOB] certifi not installed - SSL may fail')
	except Exception as e:
		print(f'[WOB] SSL config warning: {e}')

	# 1. Import qrcode
	try:
		import qrcode
		print('[WOB] qrcode import OK')
	except ImportError:
		print('[WOB] qrcode not installed. Run op("wob_setup").module.install() first.')
		return

	# 2. Cloudflare tunnel (for cross-network access) - fallback to local IP on failure
	url = None
	try:
		# Suppress tqdm progress bar output
		os.environ['TQDM_DISABLE'] = '1'
		import sys
		from contextlib import redirect_stdout, redirect_stderr
		from pycloudflared import try_cloudflare
		print('[WOB] Starting Cloudflare tunnel... (no signup required)')
		# Redirect stdout/stderr to suppress tqdm progress bars during cloudflared download
		with open(os.devnull, 'w') as devnull:
			with redirect_stdout(devnull), redirect_stderr(devnull):
				result = try_cloudflare(port=port)
				url = result.tunnel
		print(f'[WOB] Cloudflare URL: {url}')
	except ImportError:
		print('[WOB] pycloudflared not installed. Run op("wob_setup").module.install() first.')
	except Exception as e:
		print(f'[WOB] Cloudflare tunnel failed: {e} - falling back to local')

	if url is None:
		ip = get_local_ip()
		url = f'https://{ip}:{port}'
		print(f'[WOB] Local fallback URL (same network only): {ip}:{port}')

	op('/').store('wob_url', url)  # Store URL internally for callbacks.py

	# Build QR URL: point directly to GitHub Pages with ?td= parametereter
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

	# 6. Set Web Render TOP URL to cam_receiver (web-deployed, no local file needed)
	try:
		web_render = op('web_render_top')
		if web_render is not None:
			GITHUB_PAGES_URL = 'https://studio-edul.github.io/Web-Osc-Bridge/'
			receiver_url = GITHUB_PAGES_URL + 'cam_receiver.html?port=' + str(port)
			# Add tls=1 if Web Server DAT has TLS enabled (par.secure or par.tls)
			web_srv = op('web_server_dat')
			if web_srv is not None:
				tls_on = bool(getattr(web_srv.par, 'secure', False) or getattr(web_srv.par, 'tls', False))
				if tls_on:
					receiver_url += '&tls=1'
			web_render.par.url = receiver_url
			print(f'[WOB] web_render_top URL set: {receiver_url}')
		else:
			print('[WOB] web_render_top not found - create a Web Render TOP named "web_render_top"')
	except Exception as e:
		print(f'[WOB] web_render_top URL set failed: {e}')

	print('[WOB] generate() done')
