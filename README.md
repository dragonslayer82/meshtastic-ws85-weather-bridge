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
