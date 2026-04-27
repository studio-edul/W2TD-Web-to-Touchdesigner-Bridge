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

**`webrtc_video_container`** — Camera uplink pipeline (one chain per connected slot):

| Node | Type | Name | Purpose |
|------|------|------|---------|
| DAT Execute | DAT | `cam_render_sync` | Watches `sensor_table` → manages per-slot nodes |
| Layout TOP | TOP | `layout1` | Composites all slots (auto-created when slots connect) |

Auto-created per slot: `web_render_top_{N}` → `transform_top_{N}` → `crop_top_{N}` → `video_received_slot{N}` (null TOP) → `layout1`.

**`webrtc_video_tx_container`** _(Pro only)_ — Per-slot video downlink. Auto-created per slot:
`select_video_slot{N}` → `flip_top_{N}` → `video_stream_out_{N}`. Source TOPs named `video_slot{N}` are placed one level above (inside `W2TD_Pro`) by the user.

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
| `Audio` | `1` | _(Pro)_ Enable per-slot audio downlink TX |
| `Video` | `1` | _(Pro)_ Enable per-slot video downlink TX |

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
- Video downlink (Pro): TD `addTrack()` (video) → `webrtc_video_tx_container/video_stream_out_{N}` → mobile `<video>` playback
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

```python
# Send color to a specific slot
op('web_server_dat').module.send_bg_color_to_client(op('web_server_dat'), slot=1, color='#ff0000', duration=0)

# Send same color to all devices
op('web_server_dat').module.send_bg_color_to_all(op('web_server_dat'), color='#ff0000', duration=100)
```

**CHOP-driven control (`background_chop_exec.py`):**
- Create a CHOP Execute DAT, set CHOPs: `w2td_background w2td_bg_color_bus`, Value Change: On
- `w2td_background` — channels `r`, `g`, `b` (0-1, single sample) → broadcasts the same color to all clients
- `w2td_bg_color_bus` — channels `slot1_r`, `slot1_g`, `slot1_b`, `slot2_r`, ... (0-1) → per-slot routing

## TD Flashlight API (Pro)

Rear camera must be active on the mobile device.

```python
op('web_server_dat').module.send_flashlight_to_client(op('web_server_dat'), slot=1, state=1)
op('web_server_dat').module.send_flashlight_to_all(op('web_server_dat'), state=0)
```

**CHOP-driven (`flashlight_chop_exec.py`):**
- CHOP named `w2td_flashlight`, channels `slot1`, `slot2`, ... or `all` (0/1).

## TD Video Downlink (Pro)

1. Create a TOP named `video_slot{N}` inside `W2TD_Pro` (one per target slot) — feed whatever TD output you want to stream.
2. When slot `N` connects via WebRTC, `webrtc_table_sync.py` auto-creates inside `webrtc_video_tx_container`:
   `select_video_slot{N}` (pulls `../../video_slot{N}`) → `flip_top_{N}` (flipX) → `video_stream_out_{N}` (WebRTC mode).
3. TD calls `addTrack(conn_id, 'video_out_{N}', 'video')` + `createOffer` to renegotiate the existing peer connection.

On the mobile side:
- `dev_mode=1` → "TD Stream" button appears when a video track is received → tap to view fullscreen monitor
- `dev_mode=0` → video plays as a fullscreen background behind the touch pad

---

## Features

- Motion sensor (accelerometer + gyroscope) — raw m/s² and deg/s
- Device orientation (yaw/pitch/roll) — raw degrees
- Multi-touch tracking (position normalized 0~1)
- GPS (latitude / longitude)
- **Microphone** — WebRTC → Audio Stream In CHOP (uplink)
- **Camera** — WebRTC → per-slot Web Render TOP (rear/front, mutually exclusive per device), with transform + crop + layout compositing
- **Audio downlink** _(Pro)_ — TD Audio Stream Out CHOP → WebRTC → mobile speaker (per-slot routing via `w2td_audio_bus`)
- **Video downlink** _(Pro)_ — TD Video Stream Out TOP → WebRTC → mobile `<video>` (source: `video_slot{N}` TOP; dev_mode=1: monitor overlay, dev_mode=0: fullscreen background)
- **Haptic feedback** _(Pro)_ — pattern-based or continuous, driven by `w2td_haptic` CHOP or Python API
- **Background color** _(Pro)_ — broadcast via `w2td_background` (r/g/b) or per-slot via `w2td_bg_color_bus` (channels `slot{N}_r/g/b`)
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
    app.js                   ← + bg color, flashlight, TD-stream monitor
    webrtc.js                ← + handleOffer (TD-initiated audio/video downlink)
    websocket.js             ← + haptic, bg_color, flashlight callbacks
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
  callbacks.py               ← + webrtc_reoffer/reanswer handlers, auto track select
  webrtc_callbacks.py        ← + onOffer (TD-initiated offer sending)
  webrtc_table_sync.py       ← + audio/video TX routing (Select → flip → Stream Out)
  background_chop_exec.py    ← w2td_background / w2td_bg_color_bus → bg_color msgs
  haptic_chop_exec.py        ← w2td_haptic → haptic state msgs
  flashlight_chop_exec.py    ← w2td_flashlight → flashlight msgs
  update_execs.py            ← Dev utility (touch Execute DAT files to reload)
  w2td_zombie_checker.py     ← Cleans up stale slots
  (config_watch, cam_render_sync, w2td_init same as free but with W2TD_Pro base)
```

> **Workflow:** Only `docs/` and `docs-pro/` are pushed to GitHub / hosted. Python files are applied directly in TD — TD reads them live from disk.

---

## References

- [Web Server DAT — TouchDesigner Docs](https://docs.derivative.ca/Web_Server_DAT)
- [WebRTC DAT — TouchDesigner Docs](https://docs.derivative.ca/WebRTC_DAT)
- [Device Orientation API — MDN](https://developer.mozilla.org/en-US/docs/Web/API/DeviceOrientationEvent)
- [Device Motion API — MDN](https://developer.mozilla.org/en-US/docs/Web/API/DeviceMotionEvent)
