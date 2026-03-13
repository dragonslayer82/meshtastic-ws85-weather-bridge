# Meshtastic WS85 Weather Bridge

Python bridge for Meshtastic weather telemetry from a WS85 station.

It listens for weather telemetry, filters selected node IDs, writes local logs, and uploads supported values to Weather Underground.

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

This is now version 1.6.3.2.
Main cleanup in this version:
- bumped version from 1.6.3.1 to 1.6.3.2
- removed duplicate notes in this document
- cleaned up the Python script structure
- fixed the raw log newline write
- kept Weather Underground credentials in a separate config file
- kept support for both signed and unsigned Dragonslayer node IDs
-kept support for both environmentMetrics and environment_metrics
- locked the weather field list to the actual WS85-style names seen in live packets
- improved the readable CSV log so it is short and human-friendly again
- kept the noisy raw JSON log for troubleshooting
- kept current reconnect behavior
- kept current packet error handling with traceback output
- kept the Weather Underground behavior where wind, gust, direction, and 1-hour rain send zero-style defaults when absent so graphs keep getting points
- kept rainfall24h local only for now (until main meshtastic firmware is fixed)
