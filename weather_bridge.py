#!/home/edward/weather_env/bin/python3
# Meshtastic Weather Bridge
# Version: 1.5.0

import csv
import glob
import html
import json
import logging
import os
import time
import traceback
from datetime import datetime
from logging.handlers import RotatingFileHandler
from zoneinfo import ZoneInfo

import requests
from meshtastic.serial_interface import SerialInterface
from pubsub import pub

# =========================
# VERSION
# =========================

SCRIPT_VERSION = "1.5.0"

# =========================
# USER SETTINGS
# =========================

SERIAL_GLOBS = [
    "/dev/serial/by-id/*",
    "/dev/ttyUSB*",
    "/dev/ttyACM*",
]

CONFIG_FILE = "/home/edward/.weather_bridge.conf"
LOG_DIR = "/home/edward/weather_bridge_logs"
CSV_FILE = os.path.join(LOG_DIR, "earthship_history.csv")
RAW_LOG_FILE = os.path.join(LOG_DIR, "earthship_raw.jsonl")
DASHBOARD_FILE = os.path.join(LOG_DIR, "weather_bridge_dashboard.html")

# Dragonslayer node IDs
TARGET_NODE_IDS = {
    2516199244,
    -1778768052,
}

# Upload rate limit
MIN_UPLOAD_INTERVAL_SECONDS = 45

# Request timeout
HTTP_TIMEOUT = 15

# Weather Underground URL
WU_URL = "https://weatherstation.wunderground.com/weatherstation/updateweatherstation.php"

# Pacific time for saved timestamps
PACIFIC_TZ = ZoneInfo("America/Los_Angeles")

# Actual WS85-style telemetry field names seen in live packets
WS85_FIELDS = {
    "temperature": "temperature",
    "voltage": "voltage",
    "wind_direction": "windDirection",
    "wind_speed": "windSpeed",
    "wind_gust": "windGust",
    "wind_lull": "windLull",
    "rain_1h": "rainfall1h",
    "rain_24h": "rainfall24h",
    "uv_index": "uvIndex",
}

# =========================
# INTERNAL STATE
# =========================

APP_STATE = {
    "last_upload_time": 0,
    "active_serial_path": "",
    "radio_status": "starting",
    "last_serial_attempt": "",
    "last_serial_error": "",
    "last_connect_time": "",
    "last_packet_time": "",
    "last_packet_from": "",
    "last_wu_status": "never uploaded",
    "last_wu_http_status": "",
    "last_wu_success_time": "",
    "last_wu_error": "",
    "last_wu_response": "",
    "last_packet_error": "",
}

# Keep this readable. Raw JSON log is the troubleshooting log.
CSV_HEADERS = [
    "timestamp_pacific",
    "from_node",
    "temp_f",
    "voltage",
    "wind_mph",
    "gust_mph",
    "lull_mph",
    "wind_direction",
    "rain_1h_in",
    "rain_24h_in",
    "uv_index",
]

# =========================
# RAW LOG ROTATION
# =========================

raw_logger = logging.getLogger("RawPacketLogger")
raw_logger.setLevel(logging.INFO)
raw_logger.propagate = False

# =========================
# HELPERS
# =========================

def now_pacific_str():
    return datetime.now(PACIFIC_TZ).strftime("%Y-%m-%d %H:%M:%S %Z")


def load_config():
    if not os.path.exists(CONFIG_FILE):
        raise FileNotFoundError(f"Missing config file: {CONFIG_FILE}")

    config = {}
    with open(CONFIG_FILE, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            config[key.strip()] = value.strip()

    wu_station_id = config.get("WU_STATION_ID", "")
    wu_password = config.get("WU_PASSWORD", "")

    if not wu_station_id or not wu_password:
        raise ValueError("Config file must contain WU_STATION_ID and WU_PASSWORD")

    return wu_station_id, wu_password


def temp_c_to_f(temp_c):
    return (temp_c * 1.8) + 32


def mps_to_mph(value_mps):
    return value_mps * 2.237


def mm_to_inches(value_mm):
    return value_mm * 0.03937


def to_float(value, default=None):
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def ensure_csv_exists():
    if not os.path.exists(CSV_FILE):
        with open(CSV_FILE, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(CSV_HEADERS)


def ensure_log_dir_exists():
    os.makedirs(LOG_DIR, exist_ok=True)


def setup_raw_logger():
    if raw_logger.handlers:
        return

    handler = RotatingFileHandler(
        RAW_LOG_FILE,
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
    )
    handler.setFormatter(logging.Formatter("%(message)s"))
    raw_logger.addHandler(handler)


def append_raw_log(packet):
    raw_logger.info(json.dumps(packet, default=str))


def expand_serial_candidates():
    expanded = []
    for pattern in SERIAL_GLOBS:
        matches = sorted(glob.glob(pattern))
        expanded.extend(matches)

    deduped = []
    seen = set()
    for path in expanded:
        if path not in seen:
            deduped.append(path)
            seen.add(path)
    return deduped


def tail_lines(path, line_count=25):
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()
    return [line.rstrip("\n") for line in lines[-line_count:]]


def read_recent_csv_rows(limit=8):
    if not os.path.exists(CSV_FILE):
        return []

    with open(CSV_FILE, "r", newline="", encoding="utf-8", errors="replace") as f:
        rows = list(csv.DictReader(f))

    return rows[-limit:]


def render_dashboard():
    serial_candidates = expand_serial_candidates()
    recent_rows = read_recent_csv_rows(limit=8)
    raw_tail = tail_lines(RAW_LOG_FILE, line_count=20)

    rows_html = ""
    if recent_rows:
        for row in reversed(recent_rows):
            rows_html += (
                "<tr>"
                f"<td>{html.escape(row.get('timestamp_pacific', ''))}</td>"
                f"<td>{html.escape(row.get('from_node', ''))}</td>"
                f"<td>{html.escape(row.get('temp_f', ''))}</td>"
                f"<td>{html.escape(row.get('wind_mph', ''))}</td>"
                f"<td>{html.escape(row.get('gust_mph', ''))}</td>"
                f"<td>{html.escape(row.get('wind_direction', ''))}</td>"
                f"<td>{html.escape(row.get('rain_1h_in', ''))}</td>"
                f"<td>{html.escape(row.get('uv_index', ''))}</td>"
                "</tr>"
            )
    else:
        rows_html = "<tr><td colspan='8'>No readings yet</td></tr>"

    raw_tail_html = html.escape("\n".join(raw_tail)) if raw_tail else "No raw log lines yet"

    dashboard_html = f"""<!doctype html>
<html lang='en'>
<head>
  <meta charset='utf-8' />
  <meta http-equiv='refresh' content='10' />
  <title>Meshtastic Weather Bridge Dashboard</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 20px; background: #f6f8fa; }}
    h1 {{ margin-bottom: 8px; }}
    .grid {{ display: grid; grid-template-columns: repeat(2, minmax(340px, 1fr)); gap: 14px; }}
    .card {{ background: #fff; padding: 12px; border-radius: 8px; border: 1px solid #ddd; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
    th, td {{ border: 1px solid #ddd; padding: 6px; text-align: left; }}
    th {{ background: #f0f0f0; }}
    code, pre {{ background: #111; color: #d7ffd7; padding: 10px; border-radius: 6px; overflow-x: auto; display: block; }}
    ul {{ margin: 0; padding-left: 18px; }}
  </style>
</head>
<body>
  <h1>Meshtastic Weather Bridge Dashboard</h1>
  <p>Version: <b>{html.escape(SCRIPT_VERSION)}</b> | Last rendered: <b>{html.escape(now_pacific_str())}</b></p>

  <div class='grid'>
    <div class='card'>
      <h3>Radio / Serial Status</h3>
      <ul>
        <li>Radio status: <b>{html.escape(APP_STATE.get('radio_status', ''))}</b></li>
        <li>Active serial path: <b>{html.escape(APP_STATE.get('active_serial_path', ''))}</b></li>
        <li>Last serial attempt: {html.escape(APP_STATE.get('last_serial_attempt', ''))}</li>
        <li>Last serial connect time: {html.escape(APP_STATE.get('last_connect_time', ''))}</li>
        <li>Last serial error: {html.escape(APP_STATE.get('last_serial_error', ''))}</li>
      </ul>
      <p><b>Currently detected candidate paths</b></p>
      <ul>{''.join([f'<li>{html.escape(p)}</li>' for p in serial_candidates]) or '<li>None found</li>'}</ul>
    </div>

    <div class='card'>
      <h3>Weather Underground Upload Status</h3>
      <ul>
        <li>Last WU status: <b>{html.escape(APP_STATE.get('last_wu_status', ''))}</b></li>
        <li>Last WU HTTP status: {html.escape(str(APP_STATE.get('last_wu_http_status', '')))}</li>
        <li>Last successful upload time: {html.escape(APP_STATE.get('last_wu_success_time', ''))}</li>
        <li>Last WU error: {html.escape(APP_STATE.get('last_wu_error', ''))}</li>
        <li>Last WU response body: {html.escape(APP_STATE.get('last_wu_response', ''))}</li>
      </ul>
      <p><b>Is WU failure logged?</b> Yes. Failures are printed and stored here in "Last WU error".</p>
    </div>

    <div class='card' style='grid-column: 1 / span 2;'>
      <h3>Recent Weather Readings (from CSV)</h3>
      <table>
        <thead>
          <tr>
            <th>Timestamp (Pacific)</th><th>Node</th><th>Temp F</th><th>Wind mph</th><th>Gust mph</th><th>Dir</th><th>Rain 1h in</th><th>UV</th>
          </tr>
        </thead>
        <tbody>{rows_html}</tbody>
      </table>
      <p>Last packet time: {html.escape(APP_STATE.get('last_packet_time', ''))} | From node: {html.escape(str(APP_STATE.get('last_packet_from', '')))}</p>
      <p>Last packet processing error: {html.escape(APP_STATE.get('last_packet_error', ''))}</p>
    </div>

    <div class='card' style='grid-column: 1 / span 2;'>
      <h3>Current Raw Log Tail ({html.escape(RAW_LOG_FILE)})</h3>
      <pre>{raw_tail_html}</pre>
    </div>
  </div>
</body>
</html>
"""

    with open(DASHBOARD_FILE, "w", encoding="utf-8") as f:
        f.write(dashboard_html)


def connect_serial_interface():
    candidates = expand_serial_candidates()
    if not candidates:
        APP_STATE["radio_status"] = "no serial candidates found"
        APP_STATE["last_serial_error"] = "No candidate serial devices found"
        render_dashboard()
        raise FileNotFoundError(
            "No usable Meshtastic serial device found. Checked patterns: " + ", ".join(SERIAL_GLOBS)
        )

    last_error = None
    for path in candidates:
        APP_STATE["last_serial_attempt"] = path
        try:
            print(f"Trying serial path: {path}")
            interface = SerialInterface(devPath=path)
            APP_STATE["active_serial_path"] = path
            APP_STATE["radio_status"] = "connected"
            APP_STATE["last_connect_time"] = now_pacific_str()
            APP_STATE["last_serial_error"] = ""
            print(f"Connected on serial path: {path}")
            render_dashboard()
            return interface
        except Exception as e:
            last_error = e
            APP_STATE["radio_status"] = "connect failed"
            APP_STATE["last_serial_error"] = str(e)
            print(f"Failed on {path}: {e}")

    render_dashboard()
    raise RuntimeError(
        "Found serial devices but could not connect to any of them. "
        f"Last error: {last_error}"
    )


def extract_environment_metrics(packet):
    decoded = packet.get("decoded", {})
    if decoded.get("portnum") != "TELEMETRY_APP":
        return None

    telemetry = decoded.get("telemetry", {})
    return telemetry.get("environmentMetrics") or telemetry.get("environment_metrics")


def normalize_weather(env):
    temperature_c = to_float(env.get(WS85_FIELDS["temperature"]))
    voltage = to_float(env.get(WS85_FIELDS["voltage"]))
    wind_direction = to_float(env.get(WS85_FIELDS["wind_direction"]))
    wind_speed_mps = to_float(env.get(WS85_FIELDS["wind_speed"]))
    wind_gust_mps = to_float(env.get(WS85_FIELDS["wind_gust"]))
    wind_lull_mps = to_float(env.get(WS85_FIELDS["wind_lull"]))
    rain_1h_mm = to_float(env.get(WS85_FIELDS["rain_1h"]))
    rain_24h_mm = to_float(env.get(WS85_FIELDS["rain_24h"]))
    uv_index = to_float(env.get(WS85_FIELDS["uv_index"]))

    return {
        "temperature_c": temperature_c,
        "temperature_f": temp_c_to_f(temperature_c) if temperature_c is not None else None,
        "voltage": voltage,
        "wind_direction": int(wind_direction) if wind_direction is not None else None,
        "wind_speed_mps": wind_speed_mps,
        "wind_speed_mph": mps_to_mph(wind_speed_mps) if wind_speed_mps is not None else None,
        "wind_gust_mps": wind_gust_mps,
        "wind_gust_mph": mps_to_mph(wind_gust_mps) if wind_gust_mps is not None else None,
        "wind_lull_mps": wind_lull_mps,
        "wind_lull_mph": mps_to_mph(wind_lull_mps) if wind_lull_mps is not None else None,
        "rain_1h_mm": rain_1h_mm,
        "rain_1h_in": mm_to_inches(rain_1h_mm) if rain_1h_mm is not None else None,
        "rain_24h_mm": rain_24h_mm,
        "rain_24h_in": mm_to_inches(rain_24h_mm) if rain_24h_mm is not None else None,
        "uv_index": uv_index,
    }


def append_csv_row(from_node, weather):
    timestamp_pacific = datetime.now(PACIFIC_TZ).strftime("%Y-%m-%d %H:%M:%S")
    row = [
        timestamp_pacific,
        from_node,
        f"{weather['temperature_f']:.1f}" if weather["temperature_f"] is not None else "",
        f"{weather['voltage']:.2f}" if weather["voltage"] is not None else "",
        f"{weather['wind_speed_mph']:.1f}" if weather["wind_speed_mph"] is not None else "",
        f"{weather['wind_gust_mph']:.1f}" if weather["wind_gust_mph"] is not None else "",
        f"{weather['wind_lull_mph']:.1f}" if weather["wind_lull_mph"] is not None else "",
        weather["wind_direction"] if weather["wind_direction"] is not None else "",
        f"{weather['rain_1h_in']:.2f}" if weather["rain_1h_in"] is not None else "",
        f"{weather['rain_24h_in']:.2f}" if weather["rain_24h_in"] is not None else "",
        f"{weather['uv_index']:.1f}" if weather["uv_index"] is not None else "",
    ]

    with open(CSV_FILE, "a", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(row)


def build_wu_params(weather, wu_station_id, wu_password):
    """
    Send Weather Underground values from the current packet.
    For wind, gust, direction, and 1-hour rain, send zero-style defaults
    when absent so WU graphs continue receiving points.
    """
    params = {
        "ID": wu_station_id,
        "PASSWORD": wu_password,
        "action": "updateraw",
        "dateutc": "now",
        "softwaretype": f"MeshtasticWeatherBridge-{SCRIPT_VERSION}",
    }

    if weather["temperature_f"] is not None:
        params["tempf"] = round(weather["temperature_f"], 2)

    params["windspeedmph"] = round(weather["wind_speed_mph"] or 0.0, 2)
    params["windgustmph"] = round(weather["wind_gust_mph"] or 0.0, 2)
    params["winddir"] = weather["wind_direction"] or 0
    params["rainin"] = round(weather["rain_1h_in"] or 0.0, 4)

    if weather["uv_index"] is not None:
        params["UV"] = round(weather["uv_index"], 2)

    return params


def upload_to_wu(weather, wu_station_id, wu_password):
    now = time.time()
    if now - APP_STATE["last_upload_time"] < MIN_UPLOAD_INTERVAL_SECONDS:
        return

    params = build_wu_params(weather, wu_station_id, wu_password)
    useful_keys = {"tempf", "windspeedmph", "windgustmph", "winddir", "rainin", "UV"}
    if not any(k in params for k in useful_keys):
        print("No current packet values to upload; skipping WU upload")
        APP_STATE["last_wu_status"] = "skipped: no uploadable values"
        render_dashboard()
        return

    try:
        response = requests.get(WU_URL, params=params, timeout=HTTP_TIMEOUT)
        print(f"WU upload status={response.status_code} body={response.text.strip()}")
        APP_STATE["last_upload_time"] = now
        APP_STATE["last_wu_status"] = "success"
        APP_STATE["last_wu_http_status"] = str(response.status_code)
        APP_STATE["last_wu_success_time"] = now_pacific_str()
        APP_STATE["last_wu_error"] = ""
        APP_STATE["last_wu_response"] = response.text.strip()
    except requests.RequestException as e:
        print(f"WU upload failed: {e}")
        APP_STATE["last_wu_status"] = "failed"
        APP_STATE["last_wu_error"] = str(e)
        APP_STATE["last_wu_response"] = ""

    render_dashboard()


def print_weather_summary(from_node, weather):
    parts = [f"Node {from_node}"]

    if weather["temperature_f"] is not None:
        parts.append(f"Temp {weather['temperature_f']:.1f}F")
    else:
        parts.append("Temp n/a")

    if weather["wind_speed_mph"] is not None:
        parts.append(f"Wind {weather['wind_speed_mph']:.1f} mph")
    else:
        parts.append("Wind n/a")

    if weather["wind_gust_mph"] is not None:
        parts.append(f"Gust {weather['wind_gust_mph']:.1f} mph")
    else:
        parts.append("Gust n/a")

    if weather["wind_direction"] is not None:
        parts.append(f"Dir {weather['wind_direction']}")
    else:
        parts.append("Dir n/a")

    if weather["rain_1h_in"] is not None:
        parts.append(f"Rain1h {weather['rain_1h_in']:.2f} in")
    else:
        parts.append("Rain1h n/a")

    if weather["rain_24h_in"] is not None:
        parts.append(f"Rain24h {weather['rain_24h_in']:.2f} in")
    else:
        parts.append("Rain24h n/a")

    print(" | ".join(parts))

# =========================
# PACKET HANDLER
# =========================

def on_receive(packet, interface, wu_station_id, wu_password):
    try:
        append_raw_log(packet)

        from_node = packet.get("from")
        if from_node not in TARGET_NODE_IDS:
            return

        env = extract_environment_metrics(packet)
        if not env:
            return

        weather = normalize_weather(env)
        APP_STATE["last_packet_time"] = now_pacific_str()
        APP_STATE["last_packet_from"] = str(from_node)
        APP_STATE["last_packet_error"] = ""
        print_weather_summary(from_node, weather)
        append_csv_row(from_node, weather)
        upload_to_wu(weather, wu_station_id, wu_password)
        render_dashboard()

    except Exception as e:
        print(f"Packet processing error: {e}")
        print(f"Packet from node: {packet.get('from')}")
        APP_STATE["last_packet_error"] = str(e)
        render_dashboard()
        traceback.print_exc()

# =========================
# MAIN
# =========================

def main():
    wu_station_id, wu_password = load_config()
    ensure_log_dir_exists()
    setup_raw_logger()
    ensure_csv_exists()
    render_dashboard()

    print(f"Starting Meshtastic weather bridge v{SCRIPT_VERSION}")
    print(f"Serial search patterns: {SERIAL_GLOBS}")
    print(f"Target node IDs: {TARGET_NODE_IDS}")
    print(f"Log directory: {LOG_DIR}")
    print(f"CSV log: {CSV_FILE}")
    print(f"Raw log: {RAW_LOG_FILE} with 5MB rotation and 3 backups")
    print(f"Dashboard: {DASHBOARD_FILE}")
    print(f"Config file: {CONFIG_FILE}")
    print("Readable CSV timestamps are saved in Pacific time")
    print("Expected WS85 fields: temperature, voltage, windDirection, windSpeed, windGust, windLull, rainfall1h, rainfall24h, uvIndex")

    pub.subscribe(lambda packet, interface: on_receive(packet, interface, wu_station_id, wu_password), "meshtastic.receive")

    interface = None
    while True:
        try:
            interface = connect_serial_interface()
            APP_STATE["radio_status"] = "connected/listening"
            render_dashboard()
            print("Listening for packets...")

            while True:
                time.sleep(1)

        except KeyboardInterrupt:
            print("Stopping by user request")
            APP_STATE["radio_status"] = "stopped by user"
            render_dashboard()
            break

        except Exception as e:
            print(f"Serial/interface error: {e}")
            print("Retrying in 10 seconds...")
            APP_STATE["radio_status"] = "serial/interface error"
            APP_STATE["last_serial_error"] = str(e)
            render_dashboard()
            time.sleep(10)

        finally:
            try:
                if interface:
                    interface.close()
            except Exception:
                pass


if __name__ == "__main__":
    main()
