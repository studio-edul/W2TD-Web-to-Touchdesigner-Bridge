# W2TD — Integrated Web-to-TouchDesigner Bridge

> v1.0.0

Stream mobile browser sensors, audio, and camera to TouchDesigner in real time via WebSocket + WebRTC.

```
[Mobile Browser] ──WebSocket (WSS)──> [Cloudflare Tunnel] ──> [TouchDesigner Web Server DAT]
  GitHub Pages (HTTPS)                                            Port 9980 (TLS OFF)

[Mobile Mic]    ──WebRTC (P2P)──> [TD WebRTC DAT] ──> Audio Stream In CHOP
[TD Audio Out]  ──WebRTC (P2P)──> [Mobile Browser] ──> <audio> playback   (w2td_audio_bus)
[TD Video Out]  ──WebRTC (P2P)──> [Mobile Browser] ──> <video> display     (w2td_video_bus)
[Mobile Camera] ──WebRTC (P2P)──> [TD Web Render TOP] (cam_receiver.html)
```

No custom server or certificate setup required on mobile.

---

## Quick Start

### 1. TouchDesigner Setup

#### Base container

All TD nodes live inside a base COMP named `W2TD` (free) or `W2TD_Pro` (pro).

#### Top-level nodes (inside `W2TD` / `W2TD_Pro`)

| Node | Type | Name | Purpose |
|------|------|------|---------|
| Web Server DAT | DAT → Web Server | `web_server_dat` | Receives WebSocket connections |
| Callbacks Script | DAT → Text | `callbacks` | `callbacks.py` content |
| Execute DAT | DAT → Execute | `w2td_init` | `w2td_init.py` — runs on startup |
| Table DAT | DAT → Table | `sensor_table` | Auto-populated by `_init_tables()` |
| Table DAT | DAT → Table | `touch_table` | Auto-populated by `_init_tables()` |
| Table DAT | DAT → Table | `w2td_config` | Runtime configuration (key / value) |
| DAT Execute | DAT | `config_watch` | Watches `w2td_config` changes → auto broadcast |
| Text DAT | DAT → Text | `cam_receiver_html` | `cam_receiver.html` content — served via HTTP |
| Movie File In TOP | TOP | `qr_movie_top` | Displays generated QR code (optional) |

#### Sub-containers (inside `W2TD` / `W2TD_Pro`)

**`webrtc_audio_container`** — WebRTC audio RX and per-slot audio TX nodes:

| Node | Type | Name | Purpose |
|------|------|------|---------|
| WebRTC DAT | DAT → WebRTC | `webrtc_dat` | All WebRTC connections (mic + audio/video downlink) |
| Text DAT | DAT → Text | `webrtc_callbacks` | `webrtc_callbacks.py` content |
| Table DAT | DAT → Table | `webrtc_table` | Slot / conn_id / state map |
| DAT Execute | DAT | `webrtc_table_sync` | Watches `webrtc_table` → creates/destroys stream nodes |
| Merge CHOP | CHOP | `webrtc_audio_merge` | Merges all per-slot Audio Stream In CHOPs |
| Rename CHOP | CHOP | `rename1` | Renames merged channels to device names |
| Constant CHOP | CHOP | `w2td_audio_bus` | _(optional, Pro)_ per-slot audio input (channels: `slot1`, `slot2`, …) |

Auto-created per slot inside this container (by `webrtc_table_sync`):
- `webrtc_audio_{N}` — Audio Stream In CHOP (mic uplink)
- `select_slot{N}` + `webrtc_audio_out_{N}` — Audio Stream Out CHOP (Pro audio downlink)

**`webrtc_video_container`** — Camera uplink pipeline (free + Pro):

| Node | Type | Name | Purpose |
|------|------|------|---------|
| DAT Execute | DAT | `cam_render_sync` | Watches `sensor_table` → manages per-slot camera nodes |
| DAT Execute | DAT | `webrtc_video_sync` | _(Pro only)_ Watches `webrtc_table` → manages per-slot video TX nodes |
| Layout TOP | TOP | `layout1` | Composites all camera slots (auto-created when slots connect) |

Camera uplink (auto-created per slot by `cam_render_sync` — free + Pro):
`web_render_top_{N}` → `transform_top_{N}` → `crop_top_{N}` → `camera_slot{N}` (null TOP) → `layout1`

Video TX downlink (auto-created per slot by `webrtc_video_sync` — Pro only):
`select_video_slot{N}` → `flip_top_{N}` → `video_stream_out_{N}`. Source TOPs named `video_slot{N}` are placed outside `W2TD_Pro` (e.g. in `project1`) by the user.

**Web Server DAT settings:**
- Active: `On`
- Port: `9980`
- TLS: `Off`

#### w2td_config (Table DAT)

Columns: `key` | `value`. Changes are debounced and broadcast automatically by `config_watch`.

| key | default | description |
|-----|---------|-------------|
| `Maxclients` | `20` | Max simultaneous devices |
| `Samplerate` | `30` | Default sensor Hz |
| `Wakelock` | `1` | Prevent mobile screen sleep |
| `Devmode` | `1` | `1` = full UI, `0` = minimal touch-pad only |
| `Motion` `Orientation` `Geolocation` `Touch` | `1` / `1` / `0` / `1` | Per-sensor enable |
| `Rearcamera` `Frontcamera` `Microphone` | `0` / `0` / `1` | Per-stream auto-enable |
| `Echocancellation` `Noisesuppression` `Audiogain` | `0` | Mic processing (`0` = raw) |
| `Showdots` | `1` | Draw touch points on touch pad |
| `Resolution` | `Non-Commercial` | Camera square: `Non-Commercial` (1280×1280), `FHD` (1920×1920) |
| `Screenmode` | `Portrait` | Camera: `Portrait`, `Landscape` |
| `Port` | `9980` | Web server port |
| `Fixedurl` | _(optional)_ | Named Cloudflare tunnel URL — skip random tunnel |
| `Turnserver` `Turnusername` `Turnpassword` | _(optional)_ | Custom TURN server |
| `ice_transport_policy` | _(optional)_ | `relay` = force TURN only |
| `Backgroundcolor` | `1` | _(Pro)_ Enable background-color push |
| `Flashlight` | `1` | _(Pro)_ Enable flashlight control |
| `Hapticfeedback` | `1` | _(Pro)_ Enable haptic from CHOP |
| `Video` | `1` | _(Pro)_ Enable per-slot video downlink TX |
| `Videoout` | `none` | _(Pro)_ Mobile display mode: `none` = off, `color` = background color control, `js` = live JS canvas sketch, `td` = TD video stream. Also accepted as `Video` key. Changes are broadcast live (no reconnect needed). |
| `Jsfile` | _(optional)_ | _(Pro)_ Absolute path to a `.js` sketch file. When `Videoout=js`, `config_watch` reads this file and sends `canvas_code` to all clients on config change. |
| `Canvastopbar` | `1` | _(Pro)_ Show/hide top bar during JS sketch (`0` = hide, `1` = show) |

#### w2td_init.py (Execute DAT)

Copy `touchdesigner/py/w2td_init.py` (or `touchdesigner-pro/py/w2td_init.py`) into an Execute DAT named `w2td_init`.
- `onCreate()` — auto-installs Python packages (`certifi`, `qrcode[pil]`, `pycloudflared`, `scipy`) via `install_packages()`
- `onStart()` — configures SSL, resets slot state, initializes tables + WebRTC ICE, starts Cloudflare tunnel, generates QR code

Restart TD once after the first `onCreate` to ensure SSL certificates load cleanly on macOS.

#### callbacks.py (Web Server DAT Callbacks)

Copy `touchdesigner/py/callbacks.py` (or the Pro equivalent) into the Web Server DAT's Callbacks Script DAT.

### 2. Mobile Connection

1. Launch TD — `w2td_init.py` starts Cloudflare tunnel and generates QR code
2. Scan QR with your phone → opens the hosted web app with `?td=` pre-filled
   - Free: `https://w2td.studio-edul.com/`
   - Pro:  `https://w2td-pro.studio-edul.com/`
3. Enter a device name (optional) → tap **Connect**
4. Sensors activate; tap **Enable Camera** or **Enable Mic** for WebRTC streams

### 3. Reading Data in TD

**sensor_table DAT** — one row per connected device (slot 1–20):

| Column | Description | Range |
|--------|-------------|-------|
| `slot` | Device slot number | 1 ~ 20 |
| `connected` | Connection status | 0 or 1 |
| `name` | Device name (user-defined or auto-detected) | string |
| `ax` `ay` `az` | Accelerometer (gravity included) | m/s² (~±15) |
| `ga` `gb` `gg` | Gyroscope rotation rate | deg/s |
| `oa` | Orientation alpha (compass/yaw) | 0 ~ 360° |
| `ob` | Orientation beta (front/back tilt) | -180 ~ 180° |
| `og` | Orientation gamma (left/right tilt) | -90 ~ 90° |
| `lat` `lon` | GPS coordinates | degrees |
| `touch_count` | Number of active touches | integer |
| `visibility` | Foreground state (1 = visible, 0 = backgrounded) | 0 or 1 |
| `css_width` `css_height` | Browser viewport size | px |
| `physical_width` `physical_height` | Physical screen size | px |
| `screen_width` `screen_height` | Screen resolution | px |
| `device_pixel_ratio` | Device pixel ratio (DPR) | float |

**touch_table DAT** — one row per active touch point:

| Column | Description |
|--------|-------------|
| `slot` | Device slot |
| `touch_id` | Touch index (0-based) |
| `x` `y` | Touch position (normalized 0~1) |
| `state` | 1 = down |

**webrtc_table DAT** — WebRTC connection state:

| Column | Description |
|--------|-------------|
| `slot` | Device slot |
| `name` | Device name |
| `conn_id` | WebRTC DAT connection UUID |
| `state` | `connecting` / `connected` / `closed` |

**Using with CHOP:**
- Connect `sensor_table` → **DAT to CHOP**
- `First Row is Names: On`, `Select Rows: By Index` → row `1` (slot 1)
- Use **Math CHOP** to remap if needed

---

## Architecture

- TD Web Server DAT listens on port `9980` (no TLS)
- `w2td_init.py` starts a Cloudflare tunnel (random or named via `Fixedurl`) → public `wss://…`
- QR code encodes `https://w2td[-pro].studio-edul.com/?td=<tunnel-host>`
- Mobile opens the hosted web app directly — WebSocket connects via the tunnel
- Mic audio (uplink): WebRTC offer/answer via WebSocket → `webrtc_dat` → `webrtc_audio_{N}` Audio Stream In CHOP
- Audio downlink (Pro): TD `addTrack()` → `createOffer()` renegotiation → `webrtc_audio_out_{N}` Audio Stream Out CHOP → mobile `<audio>` playback
- Video downlink (Pro): TD `addTrack()` (video) → `webrtc_video_container/video_stream_out_{N}` → mobile `<video>` playback
- Camera uplink: WebRTC relay via WebSocket → per-slot `web_render_top_{N}` served from the `cam_receiver_html` Text DAT (TD serves it over HTTP on port 9980)

### Persistent state

Client slot assignments are stored via `op('/').store/fetch` and survive script reloads inside TD without dropping connections.

---

## WebSocket Message Reference

### Mobile → TD

```json
{ "type": "hello" }
{ "type": "hello", "role": "cam_receiver", "slot": 1 }   // from Web Render TOP

{ "type": "sensor", "ax": -0.12, "ay": 0.34, "az": 9.76, "ga": 12.5, "gb": -3.2, "gg": 0.8,
  "oa": 183.4, "ob": -12.0, "og": 5.3, "lat": 37.5665, "lon": 126.9780 }

{ "type": "touch", "count": 2, "t0x": 0.35, "t0y": 0.72, "t0s": 1, "t1x": 0.68, "t1y": 0.45, "t1s": 1 }

{ "type": "client_name", "name": "iPhone 15" }
{ "type": "screen_info", "width": 390, "height": 844, "physicalWidth": 1179,
  "physicalHeight": 2556, "devicePixelRatio": 3.0 }

{ "type": "webrtc_offer",    "sdp": "..." }  // initial mic uplink offer
{ "type": "webrtc_reoffer",  "sdp": "..." }  // mobile-initiated renegotiation on same connection
{ "type": "webrtc_reanswer", "sdp": "..." }  // answer to TD-initiated offer (audio/video downlink)
{ "type": "webrtc_ice", "candidate": "...", "sdpMLineIndex": 0, "sdpMid": "0" }

{ "type": "webrtc_offer_cam", "sdp": "...", "camType": "rear" }   // camera offer
{ "type": "webrtc_ice_cam",   "candidate": "...", "sdpMLineIndex": 0, "sdpMid": "0", "camType": "rear" }

{ "type": "visibility", "state": "hidden" }   // mobile went to background (home button / app switch)
{ "type": "visibility", "state": "visible" }  // mobile returned to foreground

{ "type": "ping" }                   // heartbeat
```

### TD → Mobile

```json
{ "type": "ack", "slot": 1, "td_version": "1.0.0" }
{ "type": "rejected", "reason": "Server is currently full..." }

{ "type": "config", "sample_rate": 30, "dev_mode": 1, "show_dots": 1,
  "audio_tx": 1, "video_tx": 1, "cam_resolution": "non-commercial", ... }

{ "type": "haptic", "pattern": [200, 100, 200] }   // vibration pattern
{ "type": "haptic", "state": 1 }                   // continuous vibration on/off
{ "type": "bg_color", "color": "#ff0000", "duration": 0 }    // Pro
{ "type": "flashlight", "state": 1 }                          // Pro (rear cam required)

{ "type": "webrtc_answer", "sdp": "..." }        // answer to mobile offer
{ "type": "webrtc_offer",  "sdp": "..." }        // TD-initiated offer (audio/video downlink renegotiation)
{ "type": "webrtc_ice", "candidate": "...", "sdpMLineIndex": 0, "sdpMid": "0" }
{ "type": "webrtc_state", "state": "failed" }    // connection dropped

{ "type": "webrtc_answer_cam", "sdp": "...", "camType": "rear" }
{ "type": "webrtc_ice_cam",    "candidate": "...", "sdpMLineIndex": 0, "sdpMid": "0", "camType": "rear" }

{ "type": "data_ack" }    // confirms sensor/touch data received (≤1 Hz)
{ "type": "pong" }
```

---

## TD Haptic API

```python
# Send vibration pattern to a slot
op('web_server_dat').module.send_haptic_to_client(op('web_server_dat'), slot=1, pattern=[200, 100, 200])

# Send to all connected devices
op('web_server_dat').module.send_haptic_to_all(op('web_server_dat'), pattern=[200])

# Drive vibration from CHOP (call periodically from Execute DAT or Timer CHOP)
# CHOP node named 'w2td_haptic', channels: slot1, slot2, ... (value 0 or 1)
op('web_server_dat').module.broadcast_haptic_from_chop(op('web_server_dat'))
```

## TD Background Color API (Pro)

Requires `Videoout = color` in `w2td_config`. Color is applied as a full-screen background on the mobile.

```python
# Send color to a specific slot
op('web_server_dat').module.send_bg_color_to_client(op('web_server_dat'), slot=1, color='#ff0000', duration=0)

# Send same color to all devices
op('web_server_dat').module.send_bg_color_to_all(op('web_server_dat'), color='#ff0000', duration=100)
# duration: 0 = persistent, >0 = revert to transparent after N ms
```

**CHOP-driven control (`background_chop_exec.py`):**
- Create a CHOP Execute DAT, set CHOPs: `w2td_background w2td_bg_color_bus`, Value Change: On
- `w2td_background` — channels `r`, `g`, `b` (0-1, single sample) → broadcasts the same color to all clients
- `w2td_bg_color_bus` — channels `slot1_r`, `slot1_g`, `slot1_b`, `slot2_r`, ... (0-1) → per-slot routing

## TD Canvas Sketch API (Pro)

Live-inject a JavaScript sketch into the mobile browser canvas. Requires `Videoout = js` in `w2td_config`.

The sketch receives three arguments: `canvas` (HTMLCanvasElement), `requestFrame` (wrapped rAF), `getSensors()` (real-time sensor snapshot). Global libraries `gsap`, `THREE`, `p5` are available (loaded from CDN in index.html). Return a cleanup function to run on reload/stop.

```python
# Broadcast sketch to all connected mobiles
op('web_server_dat').module.send_canvas_code_to_all(op('web_server_dat'), op('my_sketch_dat'))

# Send to a specific slot
op('web_server_dat').module.send_canvas_code_to_slot(op('web_server_dat'), 1, op('my_sketch_dat'))

# Clear (stops sketch on all mobiles)
op('web_server_dat').module.clear_canvas_code(op('web_server_dat'))
```

**Auto-send via DAT input (recommended):**

Inside `W2TD_Pro`, add an `In DAT` named `js_code_in` and a `DAT Execute` pointing to `canvas_code_dat_exec.py`. Connect a Text DAT (your sketch file) to the COMP's DAT input connector. Any edit to the Text DAT is instantly broadcast to all connected mobiles.

**`getSensors()` return keys:**

| Key | Source | Notes |
|-----|--------|-------|
| `ax ay az` | Accelerometer | m/s², gravity included |
| `ga gb gg` | Gyroscope | deg/s |
| `oa ob og` | Orientation | alpha 0–360°, beta ±180°, gamma ±90° |
| `lat lon` | GPS | degrees |
| `touch_count` | Touch | integer |
| `t0x t0y t0s` … | Touch points | x/y normalized 0–1, state 1=down |

**Example sketches:**

- `touchdesigner-examples/canvas_sketches/sensor_test.js` — sensor test ball with inertia, holofoil (5 Canvas 2D layers driven by orientation), and heartbeat
- `touchdesigner-pro/sketches/particle.js` — 3000-particle system with orientation-based gravity removal, z-axis shake → launch speed, and noise turbulence. Requires both `Motion = 1` and `Orientation = 1`.

**Orientation-based gravity removal** (`particle.js`): Uses `ob` (beta) and `og` (gamma) to compute an exact gravity vector via the W3C DeviceOrientation rotation sequence and subtracts it from raw accelerometer values, giving accurate linear acceleration even at steep static tilt angles. The correct formulas derived from `g_device = Ry(-γ)·Rx(-β)·[0,0,-g]`:
- `gx = +G·sin(γ)·cos(β)`
- `gy = -G·sin(β)`
- `gz = -G·cos(β)·cos(γ)`

**z-axis → launch speed**: Linear z acceleration (phone shaken toward/away from surface) is mapped to particle initial speed via a configurable multiplier (`Z_SCALE`). A built-in debug overlay renders live linear acceleration values at the bottom of the canvas for tuning.

**Reloading JS sketches from disk**: Set `Jsfile` in `w2td_config` to the `.js` file path (or directory). After editing the file, call from TD Textport:
```python
op('web_server_dat').module.reload_jsfile(op('web_server_dat'))
```
This re-reads the file and broadcasts the new code to all connected clients instantly.

## TD Flashlight API (Pro)

Rear camera must be active on the mobile device.

```python
op('web_server_dat').module.send_flashlight_to_client(op('web_server_dat'), slot=1, state=1)
op('web_server_dat').module.send_flashlight_to_all(op('web_server_dat'), state=0)
```

**CHOP-driven (`flashlight_chop_exec.py`):**
- CHOP named `w2td_flashlight`, channels `slot1`, `slot2`, ... or `all` (0/1).

## TD Video Downlink (Pro)

1. Create a TOP named `video_slot{N}` outside `W2TD_Pro` (e.g. in `project1`, one per target slot) — feed whatever TD output you want to stream.
2. When slot `N` connects via WebRTC, `webrtc_video_sync.py` auto-creates inside `webrtc_video_container`:
   `select_video_slot{N}` (pulls `../../video_slot{N}`) → `flip_top_{N}` (flipX) → `video_stream_out_{N}` (WebRTC mode).
3. TD calls `addTrack(conn_id, 'video_out_{N}', 'video')` + `createOffer` (delayFrames=5, after audio addTrack at frame 3) to renegotiate the existing peer connection.

**Setup in TD:**
1. Add a DAT Execute DAT inside `webrtc_video_container`
2. Set `Callbacks DAT` → `webrtc_video_sync` (this script)
3. Set `DATs` → add **both**: `webrtc_table` (same container or `../webrtc_audio_container/webrtc_table`) **and** `../../w2td_config` — this ensures nodes are created/destroyed when `Videoout` changes while a client is already connected
4. Enable `Table Change`

On the mobile side:
- `dev_mode=1` → **Fullscreen button always visible** in the top-right corner. Button label reflects the active mode (`TD Stream` / `JS Sketch` / `Color View`). Grayed-out (disabled) when `Videoout=none`. Tap to enter fullscreen; tap **Exit** to return to the main UI.
- `dev_mode=0` → video plays as a fullscreen background automatically (no button shown)

---

## Features

- Motion sensor (accelerometer + gyroscope) — raw m/s² and deg/s
- Device orientation (yaw/pitch/roll) — raw degrees
- Multi-touch tracking (position normalized 0~1)
- GPS (latitude / longitude)
- **Microphone** — WebRTC → Audio Stream In CHOP (uplink)
- **Camera** — WebRTC → per-slot Web Render TOP (rear/front, mutually exclusive per device), with transform + crop + layout compositing
- **Audio downlink** _(Pro)_ — TD Audio Stream Out CHOP → WebRTC → mobile speaker (per-slot routing via `w2td_audio_bus`)
- **Video downlink** _(Pro)_ — TD Video Stream Out TOP → WebRTC → mobile `<video>` (source: `video_slot{N}` TOP; dev_mode=1: monitor overlay, dev_mode=0: fullscreen background). Requires `Videoout = td`. Managed by `webrtc_video_sync.py` (separate from audio sync).
- **Background color** _(Pro)_ — broadcast via `w2td_background` or `w2td_color` (r/g/b) or per-slot via `w2td_bg_color_bus` (channels `slot{N}_r/g/b`). Requires `Videoout = color`. Last color is saved to localStorage and instantly applied on mode switch.
- **Live JS canvas sketch** _(Pro)_ — inject JavaScript into mobile canvas from a Text DAT or `Jsfile` path. Sensor data (motion, orientation, touch) available inside the sketch via `getSensors()`. Auto-broadcast on edit via `canvas_code_dat_exec.py` or `config_watch.py` (when `Videoout=js` + `Jsfile` set). Requires `Videoout = js`.
- **Haptic feedback** — pattern-based or continuous, driven by `w2td_haptic` CHOP or Python API (available in both Free and Pro)
- **Flashlight** _(Pro)_ — driven by `w2td_flashlight` CHOP (channels `slot{N}` or `all`)
- **WebSocket Heartbeat** — auto-reconnect on connection loss
- **Data Ack** — visual confirmation of TD reception (rate-limited 1 Hz)
- **Device name** — user-defined or auto-detected from User-Agent
- **Screen info** — CSS/physical/screen resolution + DPR
- **Config push** — `w2td_config` edits are debounced and broadcast automatically by `config_watch`
- Up to `Maxclients` simultaneous devices (default 20)
- Real-time canvas visualization
- Sample rate control (5–60 Hz)
- Wake Lock (prevents screen sleep)
- Auto-reconnect with exponential backoff

---

## Project Structure

```
docs/                        ← Free web app (hosted at w2td.studio-edul.com)
  index.html
  js/
    app.js                   ← Main app controller
    sensors.js               ← Sensor detection, permissions, simulation
    websocket.js             ← WebSocket client, heartbeat, reconnect
    webrtc.js                ← WebRTC (mic + camera)
    touch.js                 ← Touch event handling
    visualization.js         ← Canvas sparkline + touch renderer

docs-pro/                    ← Pro web app (hosted at w2td-pro.studio-edul.com)
  js/
    app.js                   ← + bg color, flashlight, TD-stream monitor, Videoout mode gate
    webrtc.js                ← + handleOffer (TD-initiated audio/video downlink)
    websocket.js             ← + haptic, bg_color, flashlight, canvas_code callbacks
    canvas_runner.js         ← CanvasRunner — executes injected JS sketch in #render-canvas
    audio.js                 ← (legacy — unused, replaced by WebRTC)
    ...

touchdesigner/py/            ← Free TD scripts (W2TD base COMP)
  callbacks.py               ← Web Server DAT callbacks + Python API
  w2td_init.py               ← onCreate installs packages; onStart starts tunnel + QR
  webrtc_callbacks.py        ← WebRTC DAT callbacks
  webrtc_table_sync.py       ← Audio Stream In CHOP sync
  config_watch.py            ← Debounced broadcast on w2td_config change
  cam_render_sync.py         ← Per-slot Web Render TOP + transform/crop/layout
  w2td_zombie_checker.py     ← Cleans up stale slots

touchdesigner-pro/py/        ← Pro TD scripts (W2TD_Pro base COMP)
  callbacks.py               ← + webrtc_reoffer/reanswer handlers, canvas_code/bg_color/flashlight API
  webrtc_callbacks.py        ← + onOffer (TD-initiated offer sending)
  webrtc_table_sync.py       ← + audio TX routing (Select → Audio Stream Out)
  webrtc_video_sync.py       ← Video TX sync (webrtc_video_container) — Select → flip → Video Stream Out
  canvas_code_dat_exec.py    ← DAT Execute — watches js_code_in (In DAT) → auto-broadcast sketch
  background_chop_exec.py    ← w2td_background / w2td_bg_color_bus → bg_color msgs
  haptic_chop_exec.py        ← w2td_haptic → haptic state msgs
  flashlight_chop_exec.py    ← w2td_flashlight → flashlight msgs
  update_execs.py            ← Dev utility (touch Execute DAT files to reload)
  w2td_zombie_checker.py     ← Cleans up stale slots
  (config_watch, cam_render_sync, w2td_init same as free but with W2TD_Pro base)

touchdesigner-pro/py_korail/ ← Korail project scripts (Script CHOP / GLSL)
  line_chop.py               ← Velocity-integral sliding-window CHOP (sensor-active + visibility gate)
  line_glsl.frag             ← Line render GLSL fragment
  line_glsl_split.frag       ← Split line render GLSL fragment

touchdesigner-pro/sketches/  ← Canvas runner sketch files (.js)
  particle.js                ← Particle system with orientation-based gravity removal

touchdesigner-examples/      ← Example projects
  canvas_sketches/
    sensor_test.js           ← Sensor test: inertia ball + holofoil + heartbeat (canvas_code sketch)
    sensor_diagnostic.js     ← Sensor diagnostic: THREE.js 3D phone model + gyro rings + 2D HUD sparklines

dev-tools/load-test/
  index.html                 ← Load test tool (single-file web app, deploy independently)
```

> **Workflow:** Only `docs/` and `docs-pro/` are pushed to GitHub / hosted. Python files are applied directly in TD — TD reads them live from disk.

---

## Load Test Tool

`dev-tools/load-test/index.html` — a single-file web app for stress-testing the TD WebSocket server with N simultaneous virtual mobile devices.

- Enter the TD tunnel URL (`wss://xxxx.trycloudflare.com`) and set the number of virtual devices (1–30)
- Each virtual client follows the exact W2TD mobile protocol: `hello` → `ack` → sensor loop
- Automatically adapts to the server's `config` (sample rate, enabled sensors)
- Staggered connection: clients connect at configurable intervals to avoid connection spikes
- Deploy as a standalone HTML file — no dependencies, works from `file://` or any HTTPS host

---

## References

- [Web Server DAT — TouchDesigner Docs](https://docs.derivative.ca/Web_Server_DAT)
- [WebRTC DAT — TouchDesigner Docs](https://docs.derivative.ca/WebRTC_DAT)
- [Device Orientation API — MDN](https://developer.mozilla.org/en-US/docs/Web/API/DeviceOrientationEvent)
- [Device Motion API — MDN](https://developer.mozilla.org/en-US/docs/Web/API/DeviceMotionEvent)
