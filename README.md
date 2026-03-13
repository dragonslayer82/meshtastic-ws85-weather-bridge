# Meshtastic WS85 Weather Bridge

A Python bridge that listens for Meshtastic weather telemetry, filters for selected node IDs, logs the data locally, and uploads supported observations to Weather Underground.

This project is meant for a practical home or remote weather relay setup where Meshtastic carries telemetry back to a bridge node that has internet access.

## What it does

- Connects to a Meshtastic node over serial
- Watches for telemetry packets from selected weather nodes
- Parses supported weather values from WS85-related telemetry
- Writes local CSV history
- Writes raw packet logs for troubleshooting
- Uploads supported values to Weather Underground
- Ignores stale or invalid values

## Features

- Node filtering
- CSV history logging
- Raw JSONL packet logging
- Weather Underground upload
- Config file support
- Safer handling for missing or stale values
- Versioned script releases

## Requirements

- Python 3.10+
- A Meshtastic device connected by serial
- A weather node sending telemetry
- Weather Underground station credentials if upload is enabled

## Install

```bash
git clone https://github.com/YOUR_GITHUB_USERNAME/meshtastic-ws85-weather-bridge.git
cd meshtastic-ws85-weather-bridge
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
