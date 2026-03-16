# Meshtastic WS85 Weather Bridge

Python bridge for Meshtastic weather telemetry from a WS85 station.

It listens for weather telemetry, filters selected node IDs, writes local logs, and uploads supported values to Weather Underground.

My starting point for modifying hardware. Had no software instructions.
[Modification of the WS85 weather sensor](https://hackaday.io/project/196990-meshtastic-or-helium-ultrasonic-wx-station)

## Main files

- `weather_bridge.py` : main script
- `sample.weather_bridge.conf` : example config
- `meshtastic-weather-bridge.service` : example systemd service file

## Output files

The script writes local output files such as:
- `earthship_history.csv`
- `earthship_raw.jsonl`

These output files are normally kept local and not committed to GitHub.

## Notes

- Do not upload your real config file
- Do not commit Weather Underground credentials
- Do not commit live log files unless they are sanitized examples

## License

MIT

## What changed in this version

This is now version 1.5.0.
Main changes in this version:
- bumped version from 1.4.1 to 1.5.0
- keeps packet timestamps in Pacific time in the readable CSV
- writes logs to a dedicated directory (`/home/edward/weather_bridge_logs`) instead of cluttering the home directory
- adds a live local dashboard file (`/home/edward/weather_bridge_logs/weather_bridge_dashboard.html`) with recent weather rows, serial/radio status, WU upload status, and raw log tail
- uses a rotating raw JSON log so troubleshooting logs do not grow forever
- tries multiple serial device paths in safe order
- prefers a stable /dev/serial/by-id path first, then falls back to /dev/ttyUSB* and /dev/ttyACM*
- replaced loose globals for WU credentials and upload timing with a single APP_STATE dictionary
- kept support for both signed and unsigned Dragonslayer node IDs
- kept support for both environmentMetrics and environment_metrics
- kept reconnect behavior and traceback logging
- kept WU zero-style defaults for wind, gust, direction, and 1-hour rain when absent

## Weather fields this version expects from WS85 telemetry

These are the actual weather field names seen in live packets and used by this version:
- temperature
- voltage
- windDirection
- windSpeed
- windGust
- windLull
- rainfall1h
- rainfall24h
- uvIndex if present later

## What each file is for

Main script:
- /home/edward/weather_bridge.py
Weather Underground config:
- /home/edward/.weather_bridge.conf
Readable weather history:
- /home/edward/weather_bridge_logs/earthship_history.csv
Raw packet troubleshooting log:
- /home/edward/weather_bridge_logs/earthship_raw.jsonl
Local dashboard:
- /home/edward/weather_bridge_logs/weather_bridge_dashboard.html
Systemd service:
- /etc/systemd/system/weather-bridge.service
