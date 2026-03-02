# W2TD — Integrated Web-to-TouchDesigner Bridge

> v1.0.0

Stream mobile browser sensors, audio, and camera to TouchDesigner in real time via WebSocket + WebRTC.

```
[Mobile Browser] ──WebSocket (WSS)──> [Cloudflare Tunnel] ──> [TouchDesigner Web Server DAT]
  GitHub Pages (HTTPS)                                            Port 9980 (TLS OFF)

[Mobile Camera/Mic] ──WebRTC (P2P)──> [TouchDesigner WebRTC DAT / Web Render TOP]
```

No custom server or certificate setup required on mobile.

---

## Quick Start

### 1. TouchDesigner Setup

#### Required DATs

| Node | Type | Name | Purpose |
|------|------|------|---------|
| Web Server DAT | DAT → Web Server | `web_server_dat` | Receives WebSocket connections |
| Callbacks Script | DAT → Text | `callbacks` | `callbacks.py` content |
| Execute DAT | DAT → Execute | `w2td_init` | `w2td_init.py` — runs on startup |
| Table DAT | DAT → Table | `sensor_table` | Auto-created by `init_tables()` |
| Table DAT | DAT → Table | `touch_table` | Auto-created by `init_tables()` |
| Table DAT | DAT → Table | `w2td_config` | Runtime configuration |

#### Optional nodes (for WebRTC audio/camera)

| Node | Type | Name | Purpose |
|------|------|------|---------|
| WebRTC DAT | DAT → WebRTC | `webrtc_dat` | Handles mic WebRTC connection |
| Text DAT | DAT → Text | `webrtc_callbacks` | `webrtc_callbacks.py` content |
| Audio Stream In CHOP | CHOP | `webrtc_audio_1` | Receives mic audio stream |
| Table DAT | DAT → Table | `webrtc_table` | WebRTC slot/connection state |
| Web Render TOP | TOP | `web_render_top` | Renders `cam_receiver.html` |

**Web Server DAT settings:**
- Active: `On`
- Port: `9980`
- TLS: `Off`

#### w2td_config (Table DAT)

Create a Table DAT named `w2td_config` to override defaults without editing code:

| key | value | description |
|-----|-------|-------------|
| `max_clients` | `20` | Max simultaneous devices |
| `sample_rate` | `30` | Default sensor Hz |
| `dev_mode` | `1` | `1` = full UI, `0` = minimal auto mode |
| `haptic_enabled` | `1` | Enable haptic feedback to devices |
| `ice_servers` | _(optional)_ | Custom TURN server URL |
| `ice_username` | _(optional)_ | TURN username |
| `ice_credential` | _(optional)_ | TURN credential |

#### w2td_init.py (Execute DAT)

Copy `touchdesigner/py/w2td_init.py` into an Execute DAT named `w2td_init`.
- `onStart()` runs automatically on TD launch
- Calls `init_tables()` (creates all required tables)
- Starts Cloudflare tunnel and generates QR code

Requires Python packages (install once):
```
pip install qrcode pillow pycloudflared
```

#### callbacks.py (Web Server DAT Callbacks)

Copy `touchdesigner/py/callbacks.py` into the Web Server DAT's Callbacks Script DAT.

### 2. Mobile Connection

1. Launch TD — `w2td_init.py` starts Cloudflare tunnel and generates QR code
2. Scan QR with your phone → opens GitHub Pages with `?td=` pre-filled
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
| `trig` | Trigger button state (held = 1, released = 0) | 0 or 1 |
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
- `w2td_init.py` starts a Cloudflare tunnel → public `wss://xxxx.trycloudflare.com`
- QR code encodes `https://studio-edul.github.io/Integrated-Web-to-TouchDesigner-Bridge/?td=xxxx.trycloudflare.com`
- Mobile opens GitHub Pages directly — WebSocket connects via Cloudflare tunnel
- Mic audio: WebRTC offer/answer via WebSocket → `webrtc_dat` → Audio Stream In CHOP
- Camera: WebRTC relay via WebSocket → `web_render_top` (cam_receiver.html)

### Persistent state

Client slot assignments are stored via `op('/').store/fetch` and survive script reloads inside TD without dropping connections.

---

## WebSocket Message Reference

### Mobile → TD

```json
{ "type": "sensor", "ax": -0.12, "ay": 0.34, "az": 9.76, "ga": 12.5, "gb": -3.2, "gg": 0.8,
  "oa": 183.4, "ob": -12.0, "og": 5.3, "lat": 37.5665, "lon": 126.9780 }

{ "type": "touch", "count": 2, "t0x": 0.35, "t0y": 0.72, "t0s": 1, "t1x": 0.68, "t1y": 0.45, "t1s": 1 }

{ "type": "trigger", "value": 1 }   // button held (1) or released (0)

{ "type": "ping" }                   // heartbeat (every 5s)
```

### TD → Mobile

```json
{ "type": "ack", "slot": 1, "td_version": "1.0.0" }

{ "type": "config", "sample_rate": 30, "dev_mode": 1, ... }

{ "type": "haptic", "pattern": [200, 100, 200] }   // vibration pattern
{ "type": "haptic", "state": 1 }                   // continuous vibration on/off

{ "type": "data_ack" }    // confirms sensor/touch data received
{ "type": "pong" }        // heartbeat response
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

---

## Features

- Motion sensor (accelerometer + gyroscope) — raw m/s² and deg/s
- Device orientation (yaw/pitch/roll) — raw degrees
- Multi-touch tracking (position normalized 0~1)
- GPS (latitude / longitude)
- **Trigger button** — hold-based (1 while held, 0 on release)
- **Haptic feedback** — pattern-based or continuous, driven by TD CHOP
- **Microphone** — WebRTC → Audio Stream In CHOP
- **Camera** — WebRTC → Web Render TOP (rear/front, mutually exclusive per device)
- **WebSocket Heartbeat** — auto-reconnect on connection loss
- **Data Ack** — visual confirmation of TD reception
- **Device name** — user-defined or auto-detected from User-Agent
- **Screen info** — CSS/physical/screen resolution + DPR
- **Config push** — w2td_config table changes broadcast to all clients automatically
- Up to 20 simultaneous devices
- Real-time canvas visualization
- Sample rate control (5–60 Hz)
- Wake Lock (prevents screen sleep)
- Auto-reconnect with exponential backoff

---

## Project Structure

```
docs/                    ← GitHub Pages (web app)
  index.html
  js/
    app.js               ← Main app controller
    sensors.js           ← Sensor detection, permissions
    websocket.js         ← WebSocket client, heartbeat, reconnect
    webrtc.js            ← WebRTC (mic + camera)
    touch.js             ← Touch event handling
    visualization.js     ← Canvas sparkline renderer

touchdesigner/
  py/
    callbacks.py         ← Web Server DAT callbacks (all WebSocket logic)
    w2td_init.py         ← Execute DAT (Cloudflare tunnel, QR, table init)
    webrtc_callbacks.py  ← WebRTC DAT callbacks
    config_watch.py      ← DAT Execute (auto-broadcast on w2td_config change)
    webrtc_table_sync.py ← DAT Execute (Audio CHOP sync from webrtc_table)
    cam_render_sync.py   ← DAT Execute (Web Render TOP sync from sensor_table)
    haptic_chop_exec.py  ← Execute DAT helper for CHOP-driven haptic
  cam_receiver.html      ← Served locally; loaded in Web Render TOP for camera
```

> **Workflow:** Only `docs/` files are pushed to GitHub. Python files are applied directly in TD.

---

## References

- [Web Server DAT — TouchDesigner Docs](https://docs.derivative.ca/Web_Server_DAT)
- [WebRTC DAT — TouchDesigner Docs](https://docs.derivative.ca/WebRTC_DAT)
- [Device Orientation API — MDN](https://developer.mozilla.org/en-US/docs/Web/API/DeviceOrientationEvent)
- [Device Motion API — MDN](https://developer.mozilla.org/en-US/docs/Web/API/DeviceMotionEvent)
