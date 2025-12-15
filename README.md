# LibreWolf Overrides Exporter

This tool generates a `librewolf.overrides.cfg` file from your **current LibreWolf profile**, exporting **only stable, user‑intentional policy preferences**.

It mirrors what you see in:

> `about:config → Only show modified preferences`

while deliberately excluding runtime state, identifiers, timestamps, counters, migration flags, and UI bookkeeping.

LibreWolf settings and override precedence documentation:
https://librewolf.net/docs/settings/

---

## What is exported (examples)

Only **policy knobs** — settings that answer *“what should the browser do?”*:

- Privacy & tracking protection  
  `privacy.trackingprotection.*`, `browser.contentblocking.*`
- Network privacy  
  `beacon.enabled`, `network.trr.*`, `network.dns.*`
- Telemetry / reporting policy (not cached IDs)  
  `toolkit.telemetry.*`, `datareporting.policy.*`
- Security posture  
  `dom.security.*`, selected `security.*`
- Form autofill policy  
  `dom.forms.autocomplete.formautofill` (KeePassXC unaffected)
- DRM / EME toggle (if intentionally set)  
  `media.eme.enabled`
- Bookmarks auto‑export path (if intentionally set)  
  `browser.bookmarks.file`

---

## What is intentionally excluded

The script will **never export or pin**:

### Identifiers / per‑profile data
- `extensions.webextensions.uuids`
- `*Id`, `*UUID`, `profileId`, `storeID`, `clientID`
- Nimbus / Push / per‑install identifiers

### Timestamps, counters, lifecycle state
- `last*`, `next*`, `*_date`, `*_time`, `*_seconds`
- `browser.search.totalSearches`
- `privacy.purge_trackers.last_purge`
- `browser.startup.lastColdStartupCheck`

### UI, migration, and bookkeeping state
- `browser.uiCustomization.state`
- `browser.pageActions.persistedActions`
- `*.has-used`, `*.ever*`, `*.seen`, `*.pending`
- `extensions.*Schema`, `*migration*`

### Component / hardware bookkeeping
- `media.gmp-*`
- `gfx.blacklist.*`
- sandbox temp directory suffixes, failure IDs, hashes

---

## Command‑line flags

- `--base-dir PATH`  
  Explicit LibreWolf base directory

- `--profile-dir PATH`  
  Explicit profile directory (overrides `profiles.ini`)

- `--output PATH`  
  Output path for `librewolf.overrides.cfg`

- `--print-skipped`  
  Print skipped preferences as commented `user_pref(...)` lines for audit

---

## License

GPL‑3.0‑only. See `LICENSE`.
