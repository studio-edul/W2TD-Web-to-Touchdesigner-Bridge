# WOB — Web-to-TouchDesigner Bridge

Stream mobile browser sensors (motion, orientation, touch, GPS) to TouchDesigner in real time via WebSocket.

```
[Mobile Browser] ──WebSocket (WSS)──> [ngrok tunnel] ──> [TouchDesigner Web Server DAT]
  GitHub Pages (HTTPS)                                       Port 9980 (TLS OFF)
```

No custom server or certificate setup required on mobile.

---

## Quick Start

### 1. TouchDesigner Setup

#### Required DATs

| Node | Type | Name | Purpose |
|------|------|------|---------|
| Web Server DAT | DAT → Web Server | any | Receives WebSocket connections |
| Callbacks Script | DAT → Text | `callbacks` (set in Web Server DAT) | `callbacks.py` content |
| Execute DAT | DAT → Execute | `wob_init` | `wob_init.py` content — runs on startup |
| Table DAT | DAT → Table | `sensor_table` | Auto-created by `init_tables()` |
| Table DAT | DAT → Table | `touch_table` | Auto-created by `init_tables()` |

**Web Server DAT settings:**
- Active: `On`
- Port: `9980`
- TLS: `Off` (required for ngrok)

#### Optional config DAT

Create a **Table DAT** named `wob_config` to override defaults without editing code:

| key | value |
|-----|-------|
| max_clients | 20 |

#### wob_init.py (Execute DAT)

Copy `touchdesigner/wob_init.py` into an Execute DAT.
- `onStart()` runs automatically on TD launch
- Calls `init_tables()` (creates sensor_table / touch_table)
- Starts ngrok tunnel and generates QR code

Requires Python packages (install once via TD's Python):
```
pip install qrcode pillow pyngrok
ngrok config add-authtoken <YOUR_TOKEN>
```

#### callbacks.py (Web Server DAT Callbacks)

Copy `touchdesigner/callbacks.py` into the Web Server DAT's Callbacks Script DAT.

### 2. Mobile Connection

1. Launch TD — `wob_init.py` starts ngrok and generates a QR code (displayed on `qr_movie_top` TOP)
2. Scan QR with your phone → opens GitHub Pages directly with `?td=` pre-filled
3. Tap **Enable Sensors** → sensors activate automatically
4. Data begins streaming to TD immediately

### 3. Reading Data in TD

**sensor_table DAT** — one row per connected device (slot 1–20):

| Column | Description | Range |
|--------|-------------|-------|
| `slot` | Device slot number | 1 ~ 20 |
| `connected` | Connection status | 0 or 1 |
| `ax` `ay` `az` | Accelerometer (gravity included) | m/s² (~±15) |
| `ga` `gb` `gg` | Gyroscope rotation rate | deg/s |
| `oa` | Orientation alpha (compass/yaw) | 0 ~ 360° |
| `ob` | Orientation beta (front/back tilt) | -180 ~ 180° |
| `og` | Orientation gamma (left/right tilt) | -90 ~ 90° |
| `lat` `lon` | GPS coordinates | degrees |
| `touch_count` | Number of active touches | integer |
| `trig` | Trigger button pulse (1 for one packet) | 0 or 1 |

**touch_table DAT** — one row per active touch point:

| Column | Description |
|--------|-------------|
| `slot` | Device slot |
| `touch_id` | Touch index (0-based) |
| `x` `y` | Touch position (normalized 0~1) |
| `state` | 1 = down |

**Using with CHOP:**
- Connect `sensor_table` → **DAT to CHOP**
- Set `First Row is Names: On`, `Select Rows: By Index` → row `1` (slot 1)
- Use **Math CHOP** to remap if needed (e.g. `oa` 0~360 → 0~1)

---

## Architecture

- TD Web Server DAT listens on port `9980` (no TLS)
- `wob_init.py` starts an ngrok HTTP tunnel → public `wss://xxxx.ngrok-free.app`
- QR code encodes `https://studio-edul.github.io/Web-Osc-Bridge/?td=xxxx.ngrok-free.app`
- Mobile opens GitHub Pages directly — no ngrok interstitial page
- WebSocket connects via ngrok tunnel (`wss://`) — GitHub Pages (HTTPS) requires WSS

### Persistent state across callbacks.py reloads

Client slot assignments are stored via `op('/').store/fetch` so they survive script reloads inside TD without dropping connections.

### Multi-client

Up to `max_clients` (default 20) simultaneous devices. Slots are assigned on connect and freed on disconnect.

---

## Data Format (WebSocket JSON)

### Sensor packet (sent at configurable Hz)
```json
{
  "type": "sensor",
  "ax": -0.12, "ay": 0.34, "az": 9.76,
  "ga": 12.5,  "gb": -3.2, "gg": 0.8,
  "oa": 183.4, "ob": -12.0, "og": 5.3,
  "lat": 37.5665, "lon": 126.9780
}
```

### Touch packet
```json
{
  "type": "touch",
  "count": 2,
  "t0x": 0.35, "t0y": 0.72, "t0s": 1,
  "t1x": 0.68, "t1y": 0.45, "t1s": 1
}
```

### Trigger packet (button press)
```json
{ "type": "trigger" }
```
TD sets `sensor_table[slot, 'trig'] = 1` for one sensor cycle, then resets to 0.

---

## Features

- Motion sensor (accelerometer + gyroscope) — raw m/s² and deg/s
- Device orientation (yaw/pitch/roll) — raw degrees
- Multi-touch tracking (position normalized 0~1)
- GPS (latitude / longitude)
- Trigger button (one-shot pulse to TD)
- Up to 20 simultaneous devices
- Real-time canvas visualization (sparklines, selected sensors only)
- Sample rate control (5–60 Hz)
- Wake Lock (prevents screen sleep)
- Auto-reconnect with exponential backoff
- Settings saved to LocalStorage
- Hide/show log panel

---

## Project Structure

```
docs/               ← GitHub Pages (web app)
  index.html
  js/
    app.js          ← Main app logic, broadcast loop
    sensors.js      ← Sensor detection, permissions, raw data collection
    websocket.js    ← WebSocket client, reconnect
    visualization.js← Canvas sparkline renderer
    ui.js           ← UI helpers

touchdesigner/
  callbacks.py      ← Web Server DAT callbacks (WebSocket handling, sensor_table writes)
  wob_init.py       ← Execute DAT (ngrok startup, QR generation, table init)
```

> **Workflow:** Only `docs/` files are pushed to GitHub. Python files are applied directly in TD (file changes update the DAT automatically).

---

## References

- [Web Server DAT — TouchDesigner Docs](https://docs.derivative.ca/Web_Server_DAT)
- [Device Orientation API — MDN](https://developer.mozilla.org/en-US/docs/Web/API/DeviceOrientationEvent)
- [Device Motion API — MDN](https://developer.mozilla.org/en-US/docs/Web/API/DeviceMotionEvent)
