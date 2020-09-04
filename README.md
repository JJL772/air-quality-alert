## Air Alert

A quick and dirty python application that sends you emails when the AQI for a group of sensors goes high.

### Usage

The application is meant to be used as a daemon.

Example usage:
```
AirAlert.py --config=~/.config/air-alert.json --state-file=~/.local/share/air-alert/state.json
```

The state file, specified by the `--state-file` option, is where the application stores its state. In the event that the daemon is restarted, killed or crashes, it can start right where it left off before it died.

An example config is provided in the etc/ directory of this repository. The config must be valid and exist or else the application will not start.

### License

See LICENSE.txt