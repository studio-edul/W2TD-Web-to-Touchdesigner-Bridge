import socket
import os
import subprocess
import sys
import platform

W2TD_BASE = 'W2TD_Pro'
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
	global MAX_CLIENTS
	cfg = _read_config()
	val = cfg.get('Maxclients') or cfg.get('maxclients') or cfg.get('max_clients')
	if val:
		try:
			MAX_CLIENTS = max(1, int(val))
		except ValueError:
			pass

	# Store MAX_CLIENTS globally so other modules can access it
	op('/').store('w2td_max_clients', MAX_CLIENTS)

	# Reset persistent slot state so new connections start from slot 1
	op('/').store('w2td_client_slots', {})
	op('/').store('w2td_free_slots', list(range(1, MAX_CLIENTS + 1)))
	op('/').store('w2td_touch_count', {})
	op('/').store('w2td_client_names', {})
	op('/').store('w2td_pending_cam_offers', {})
	op('/').store('w2td_pending_cam_ice', {})
	for s in range(1, MAX_CLIENTS + 1):
		op('/').store(f'w2td_last_seen_{s}', 0)
		op('/').store(f'w2td_last_ack_{s}', 0)
		op('/').store(f'w2td_webrtc_slot_to_uuid_{s}', None)
		op('/').store(f'w2td_cam_receiver_addr_{s}', None)
		op('/').store(f'w2td_web_render_slot_{s}', None)
		op('/').store(f'w2td_cam_res_logged_{s}', False)
		op('/').store(f'w2td_screen_{s}', {})
	print(f'[W2TD] Slot state reset (max {MAX_CLIENTS} slots)')

	t = _op('sensor_table')
	if t is not None:
		t.clear()
		t.appendRow(SENSOR_COLS)
		# No pre-populated rows - rows are added on connect, removed on disconnect
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
	"""Configure WebRTC DAT TURN servers if provided via w2td_config."""
	w = _op('webrtc_audio_container/webrtc_dat', 'webrtc_dat')
	if w is None:
		return

	# Clear previous turn0/turn1 values
	_set_par(w, 'turn0server', '')
	_set_par(w, 'turn0username', '')
	_set_par(w, 'turn0credential', '', ('turn0password', 'turn0pass'))
	_set_par(w, 'turn1server', '')
	_set_par(w, 'turn1username', '')
	_set_par(w, 'turn1credential', '', ('turn1password', 'turn1pass'))

	# Check for user-provided TURN server
	cfg = _read_config()
	if cfg:
		turn_srv = (cfg.get('Turnserver') or cfg.get('turn_server') or '').strip()
		turn_user = (cfg.get('Turnusername') or cfg.get('turn_username') or '').strip()
		turn_pass = (cfg.get('Turnpassword') or cfg.get('turn_password') or '').strip()

		if turn_srv:
			_set_par(w, 'turn0server', turn_srv)
			_set_par(w, 'turn0username', turn_user, ('turn0user',))
			_set_par(w, 'turn0credential', turn_pass, ('turn0password', 'turn0pass'))
			print(f'[W2TD] WebRTC DAT ICE TURN configured: {turn_srv}')
		else:
			print('[W2TD] WebRTC DAT ICE initialization complete (No TURN server set)')
	else:
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


def _write_config(key, value):
	"""Write a value to w2td_config. Falls back to COMP parameter if parameterDAT."""
	cfg_dat = _op('w2td_config')
	if cfg_dat is None:
		return
	try:
		for r in range(1, cfg_dat.numRows):
			if str(cfg_dat[r, 0]) == key:
				cfg_dat[r, 1] = value
				return
		cfg_dat.appendRow([key, value])
	except Exception:
		base = _w2td_base()
		if base is not None:
			for par_name in (key, key.lower(), key.capitalize()):
				if hasattr(base.par, par_name):
					try:
						setattr(base.par, par_name, value)
						return
					except Exception:
						pass
		print(f'[W2TD] Could not write {key} to w2td_config or COMP parameter')


def _find_cloudflared():
	"""Find cloudflared binary from system PATH or pycloudflared cache."""
	import shutil

	found = shutil.which('cloudflared')
	if found:
		return found

	ext = '.exe' if platform.system() == 'Windows' else ''

	try:
		import pycloudflared
		pkg_dir = os.path.dirname(pycloudflared.__file__)
		for subdir in ('', 'bin'):
			candidate = os.path.join(pkg_dir, subdir, f'cloudflared{ext}')
			if os.path.isfile(candidate):
				return candidate
	except ImportError:
		pass

	home = os.path.expanduser('~')
	if platform.system() == 'Windows':
		appdata = os.environ.get('LOCALAPPDATA', home)
		candidates = [
			os.path.join(appdata, 'pycloudflared', f'cloudflared{ext}'),
			os.path.join(home, '.pycloudflared', f'cloudflared{ext}'),
		]
	else:
		candidates = [
			os.path.join(home, '.pycloudflared', f'cloudflared{ext}'),
			'/usr/local/bin/cloudflared',
			'/opt/homebrew/bin/cloudflared',
		]

	for c in candidates:
		if os.path.isfile(c):
			return c

	return None


def _monitor_tunnel_output(proc, tunnel_name, qr_url):
	"""Background thread: reads cloudflared output and logs connection status."""
	import threading
	def _read():
		try:
			for raw in proc.stdout:
				line = raw.decode('utf-8', errors='ignore').strip()
				low = line.lower()
				if 'connection established' in low or 'registered tunnel connection' in low:
					print(f'[W2TD] Tunnel "{tunnel_name}" connected — {qr_url}')
				elif 'error' in low or 'failed' in low or 'unable' in low:
					print(f'[W2TD Error] Tunnel: {line}')
				if proc.poll() is not None:
					break
		except Exception:
			pass
	t = threading.Thread(target=_read, daemon=True)
	t.start()


def start_fixed_tunnel():
	"""Start cloudflared named tunnel using Tunnelname + Url from w2td_config.
	Requires: cloudflared authenticated + tunnel created beforehand.
	Call manually: op('w2td_init').module.start_fixed_tunnel()
	"""
	cfg = _read_config()
	qr_url = (cfg.get('Url') or '').strip()
	tunnel_name = (cfg.get('Tunnelname') or cfg.get('tunnel_name') or '').strip()

	if not tunnel_name:
		print('[W2TD Error] Tunnelname not set in w2td_config.')
		print('[W2TD Error] w2td_config에 key=Tunnelname, value=<터널 이름> 행을 추가하세요.')
		return False

	existing = op('/').fetch('w2td_tunnel_proc', None)
	if existing is not None:
		try:
			if existing.poll() is None:
				print(f'[W2TD] Tunnel already running (PID {existing.pid}) — {qr_url}')
				return True
		except Exception:
			pass

	cloudflared_bin = _find_cloudflared()
	if not cloudflared_bin:
		print('[W2TD Error] cloudflared binary not found.')
		print('[W2TD Error] install_packages() 실행 후 TD를 재시작하거나 cloudflared를 수동 설치하세요.')
		return False

	kwargs = {}
	if platform.system() == 'Windows':
		kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW

	port_val = cfg.get('Port') or cfg.get('port')
	try:
		port = int(port_val) if port_val else 9980
	except (ValueError, TypeError):
		port = 9980

	try:
		proc = subprocess.Popen(
			[cloudflared_bin, 'tunnel', '--no-autoupdate', 'run', '--url', f'http://localhost:{port}', tunnel_name],
			stdout=subprocess.PIPE,
			stderr=subprocess.STDOUT,
			**kwargs
		)
		op('/').store('w2td_tunnel_proc', proc)
		print(f'[W2TD] cloudflared 프로세스 시작 (PID {proc.pid})')
		print(f'[W2TD] 터널 "{tunnel_name}" 연결 중... 잠시 후 "connected" 로그가 뜨면 정상입니다.')
		print(f'[W2TD] 고정 URL: {qr_url}')
		_monitor_tunnel_output(proc, tunnel_name, qr_url)
		return True
	except Exception as e:
		print(f'[W2TD Error] 터널 시작 실패: {e}')
		return False


def stop_tunnel():
	"""Stop running cloudflared tunnel process.
	Call manually: op('w2td_init').module.stop_tunnel()
	"""
	proc = op('/').fetch('w2td_tunnel_proc', None)
	if proc is None:
		print('[W2TD] 실행 중인 터널 프로세스 없음 — 건너뜁니다.')
		return
	try:
		pid = proc.pid
		proc.terminate()
		op('/').store('w2td_tunnel_proc', None)
		print(f'[W2TD] cloudflared 터널 종료 완료 (PID {pid})')
	except Exception as e:
		print(f'[W2TD Error] 터널 종료 실패: {e}')


def install_packages():
	"""Install required Python packages into TD's Python environment.
	This function is called automatically on onCreate, or can be called manually.
	"""
	PACKAGES = ['qrcode[pil]', 'pycloudflared', 'scipy']
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


def onExit():
	print('[W2TD] 고정 URL 터널 세팅 시작...')
	start_fixed_tunnel()


def onFrameStart(frame):
	import webbrowser
	webbrowser.open('https://www.metered.ca')

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

	# 2. Get QR URL — fixed mode (Fixedurl=1) or random Cloudflare tunnel (Fixedurl=0)
	is_fixed = str(cfg.get('Fixedurl') or '0').strip() == '1'
	qr_url = None
	short_host = None
	last_error = None

	if is_fixed:
		qr_url = (cfg.get('Url') or '').strip()
		if not qr_url:
			print('[W2TD Error] Fixedurl=1 but Url is empty in w2td_config')
			return
		if '?td=' in qr_url:
			short_host = qr_url.split('?td=')[-1].strip()
		else:
			short_host = qr_url.replace('https://', '').replace('http://', '').strip()
		print(f'[W2TD] Fixed mode: {qr_url}')
	else:
		tunnel_url = None
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
					tunnel_url = result.tunnel
					break
				except Exception as e:
					last_error = e
					if attempt < 2:
						print(f'[W2TD Error] Tunnel attempt {attempt + 1} failed: {e}')
						time.sleep(2)
					else:
						raise
			if tunnel_url:
				print(f'[W2TD] Cloudflare URL: {tunnel_url}')
		except ImportError:
			last_error = 'pycloudflared not installed'
			print('[W2TD Error] pycloudflared not installed.')
		except Exception as e:
			last_error = e

		if tunnel_url is None:
			err_msg = str(last_error) if last_error else 'Unknown error'
			print(f'[W2TD Error] Cloudflare tunnel failed: {err_msg}')
			return

		host = tunnel_url.replace('https://', '').replace('http://', '').strip()
		short_host = host.replace('.trycloudflare.com', '') if host.endswith('.trycloudflare.com') else host
		GITHUB_PAGES_URL = 'https://w2td-pro.studio-edul.com/'
		qr_url = GITHUB_PAGES_URL + '?td=' + host
		_write_config('Url', qr_url)

	op('/').store('w2td_url', qr_url)
	
	parent_comp = None
	url_par_name = 'url'
	# Try all common parent locations
	for p in [parent(), op('..'), op('../W2TD'), op('../W2TD_Pro'), _w2td_base()]:
		if p is not None:
			if hasattr(p.par, 'url'):
				parent_comp = p
				url_par_name = 'url'
				break
			elif hasattr(p.par, 'Url'):
				parent_comp = p
				url_par_name = 'Url'
				break
			
	if parent_comp:
		try:
			setattr(parent_comp.par, url_par_name, short_host)
			print(f'[W2TD] Target COMP found: {parent_comp.path}, {url_par_name} set to {short_host}')
		except Exception as e:
			print(f'[W2TD Error] W2TD.par.{url_par_name} set failed on {parent_comp.path}: {e}')
	else:
		print('[W2TD Error] Could not find parent COMP with a "url" or "Url" parameter.')
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
		op('/').store('w2td_cam_base_url', f'{scheme}://127.0.0.1:{port}')
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
