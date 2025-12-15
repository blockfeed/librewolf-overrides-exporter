# LibreWolf Overrides Exporter

Generate a `librewolf.overrides.cfg` file from the *current* LibreWolf profile’s **modified** preferences (`prefs.js` `user_pref(...)` entries), in a format compatible with LibreWolf’s settings system.

This is meant to mirror what you see in `about:config` when you enable **“Only show modified preferences”**, while avoiding pinning volatile/session prefs and identifier/cache churn.

## What it does

- Finds your LibreWolf profile via `profiles.ini` (supports non-Flatpak and Flatpak locations).
- Reads `<profile>/prefs.js` and extracts `user_pref("name", value);` entries.
- Writes them as enforced overrides: `pref("name", value);` to `librewolf.overrides.cfg`.
- Skips:
  - session/runtime churn (`browser.sessionstore.*`)
  - extension/profile bookkeeping (`extensions.*BuildId`, `extensions.*Version`, schema)
  - identifier/cache churn (`toolkit.telemetry.cached*`, `datareporting.dau.cached*`)
  - extension UUID map (`extensions.webextensions.uuids`)

## Requirements

- Python 3 (no third-party dependencies)

## Usage

Run with autodetection:

```bash
python3 lw_export_overrides.py
```

Audit what was skipped:

```bash
python3 lw_export_overrides.py --print-skipped
```

Show basic stats:

```bash
python3 lw_export_overrides.py --stats
```

Override paths explicitly:

```bash
python3 lw_export_overrides.py \
  --base-dir ~/.librewolf \
  --profile-dir ~/.librewolf/<your-profile> \
  --output ~/.librewolf/librewolf.overrides.cfg
```

Exclude additional prefs (repeatable):

```bash
python3 lw_export_overrides.py --exclude-prefix 'app.normandy.' --exclude-prefix 'app.shield.'
```

## Verification

After generating:

1. Close LibreWolf fully.
2. Start LibreWolf.
3. In `about:config`, search for a pref you know you changed (e.g. `beacon.enabled`) and confirm it matches your override.

## Notes

- This emits `pref(...)` lines, which **enforce** values at startup.
- If you want “soft defaults” instead, you can mechanically change `pref(` to `defaultPref(`, but that will no longer correspond to “modified prefs”.

## License

GPL-3.0. See `LICENSE`.
