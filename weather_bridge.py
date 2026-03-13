#!/home/edward/weather_env/bin/python3

# Meshtastic Weather Bridge
# Version: 1.6.3.2
# Major.Year.Month.Release
# 1 = major version
# 6 = 2026
# 3 = March
# 2 = second release this month

import csv
import json
import os
import time
import traceback
from datetime import datetime

import requests
from meshtastic.serial_interface import SerialInterface
from pubsub import pub

# =========================
# VERSION
# =========================

SCRIPT_VERSION = "1.6.3.2"

# =========================
# USER SETTINGS
# =========================

SERIAL_PORT = "/dev/ttyUSB0"
CONFIG_FILE = "/home/edward/.weather_bridge.conf"
CSV_FILE = "/home/edward/earthship_history.csv"
RAW_LOG_FILE = "/home/edward/earthship_raw.jsonl"

# Dragonslayer node IDs
TARGET_NODE_IDS = {
    2516199244,   # unsigned
    -1778768052,  # signed
}

# Upload rate limit
MIN_UPLOAD_INTERVAL_SECONDS = 45

# Request timeout
HTTP_TIMEOUT = 15

# Weather Underground URL
WU_URL = "https://weatherstation.wunderground.com/weatherstation/updateweatherstation.php"

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

last_upload_time = 0
WU_STATION_ID = None
WU_PASSWORD = None

# Keep this readable. Raw JSON log is the troubleshooting log.
CSV_HEADERS = [
    "timestamp_local",
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
# HELPERS
# =========================

def load_config():
    global WU_STATION_ID, WU_PASSWORD

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

    WU_STATION_ID = config.get("WU_STATION_ID")
    WU_PASSWORD = config.get("WU_PASSWORD")

    if not WU_STATION_ID or not WU_PASSWORD:
        raise ValueError("Config file must contain WU_STATION_ID and WU_PASSWORD")


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


def append_raw_log(packet):
    with open(RAW_LOG_FILE, "a") as f:
        f.write(json.dumps(packet, default=str) + "
")


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
    timestamp_local = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    row = [
        timestamp_local,
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


def build_wu_params(weather):
    """
    Send Weather Underground values from the current packet.
    For wind, gust, direction, and 1-hour rain, send zero-style defaults
    when absent so WU graphs continue receiving points.
    """
    params = {
        "ID": WU_STATION_ID,
        "PASSWORD": WU_PASSWORD,
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


def upload_to_wu(weather):
    global last_upload_time

    now = time.time()
    if now - last_upload_time < MIN_UPLOAD_INTERVAL_SECONDS:
        return

    params = build_wu_params(weather)

    useful_keys = {"tempf", "windspeedmph", "windgustmph", "winddir", "rainin", "UV"}
    if not any(k in params for k in useful_keys):
        print("No current packet values to upload; skipping WU upload")
        return

    try:
        response = requests.get(WU_URL, params=params, timeout=HTTP_TIMEOUT)
        print(f"WU upload status={response.status_code} body={response.text.strip()}")
        last_upload_time = now
    except requests.RequestException as e:
        print(f"WU upload failed: {e}")


def print_weather_summary(from_node, weather):
    summary = (
        f"Node {from_node} | "
        f"Temp {weather['temperature_f']:.1f}F | " if weather["temperature_f"] is not None else f"Node {from_node} | Temp n/a | "
    )
    summary += (
        f"Wind {weather['wind_speed_mph']:.1f} mph | " if weather["wind_speed_mph"] is not None else "Wind n/a | "
    )
    summary += (
        f"Gust {weather['wind_gust_mph']:.1f} mph | " if weather["wind_gust_mph"] is not None else "Gust n/a | "
    )
    summary += (
        f"Dir {weather['wind_direction']} | " if weather["wind_direction"] is not None else "Dir n/a | "
    )
    summary += (
        f"Rain1h {weather['rain_1h_in']:.2f} in | " if weather["rain_1h_in"] is not None else "Rain1h n/a | "
    )
    summary += (
        f"Rain24h {weather['rain_24h_in']:.2f} in" if weather["rain_24h_in"] is not None else "Rain24h n/a"
    )
    print(summary)

# =========================
# PACKET HANDLER
# =========================

def on_receive(packet, interface):
    try:
        append_raw_log(packet)

        from_node = packet.get("from")
        if from_node not in TARGET_NODE_IDS:
            return

        env = extract_environment_metrics(packet)
        if not env:
            return

        weather = normalize_weather(env)
        print_weather_summary(from_node, weather)
        append_csv_row(from_node, weather)
        upload_to_wu(weather)

    except Exception as e:
        print(f"Packet processing error: {e}")
        print(f"Packet from node: {packet.get('from')}")
        traceback.print_exc()

# =========================
# MAIN
# =========================

def main():
    load_config()
    ensure_csv_exists()

    print(f"Starting Meshtastic weather bridge v{SCRIPT_VERSION}")
    print(f"Serial port: {SERIAL_PORT}")
    print(f"Target node IDs: {TARGET_NODE_IDS}")
    print(f"CSV log: {CSV_FILE}")
    print(f"Raw log: {RAW_LOG_FILE}")
    print(f"Config file: {CONFIG_FILE}")
    print("Expected WS85 fields: temperature, voltage, windDirection, windSpeed, windGust, windLull, rainfall1h, rainfall24h, uvIndex")

    pub.subscribe(on_receive, "meshtastic.receive")

    interface = None

    while True:
        try:
            print("Connecting to Meshtastic serial interface...")
            interface = SerialInterface(devPath=SERIAL_PORT)
            print("Connected. Listening for packets...")

            while True:
                time.sleep(1)

        except KeyboardInterrupt:
            print("Stopping by user request")
            break

        except Exception as e:
            print(f"Serial/interface error: {e}")
            print("Retrying in 10 seconds...")
            time.sleep(10)

        finally:
            try:
                if interface:
                    interface.close()
            except Exception:
                pass

if __name__ == "__main__":
    main()
