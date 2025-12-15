# LibreWolf Overrides Exporter (Policy‑Only, Privacy‑First)

This tool generates a `librewolf.overrides.cfg` file from your *current* LibreWolf profile by exporting **only stable, intentional policy preferences**.

It mirrors what you see in `about:config → Only show modified preferences`, **but deliberately excludes anything that represents state, history, identifiers, timestamps, counters, or UI bookkeeping**. The goal is to enforce *what the browser should do*, not *what has happened before*.

---

## Design principles

This exporter follows a strict rule:

> **If a preference answers “what happened?” it is ignored.  
> If it answers “what should the browser do?” it may be enforced.**

Accordingly, the script:

- **Keeps** privacy posture and behavior choices (policy)
- **Drops** runtime state, migration flags, timestamps, counters, and identifiers
- Avoids pinning anything that could:
  - increase fingerprint stability
  - leak behavioral history
  - break update / cleanup logic
  - encode per‑profile identity

---

## What is exported (examples)

These are **policy knobs** and are enforced via `pref(...)`:

- Tracking protection and content blocking  
  (`privacy.trackingprotection.*`, `browser.contentblocking.*`)
- Telemetry / reporting policy  
  (`toolkit.telemetry.*`, `datareporting.policy.*`)
- Networking posture  
  (`beacon.enabled`, `network.trr.*`, `network.dns.*`)
- Security posture  
  (`dom.security.*`, `security.*`)
- Form autofill policy  
  (`dom.forms.autocomplete.formautofill` — KeePassXC unaffected)
- **EME / DRM toggle**  
  (`media.eme.enabled`, if you intentionally set it)
- **Bookmarks auto‑export path**  
  (`browser.bookmarks.file`, if you intentionally set it)

---

## What is intentionally excluded

The script **will not export or pin** any of the following, even if they appear modified:

### Identifiers
Examples:
- `*Id`, `*UUID`, `impressionId`, `profileId`, `storeID`, `clientID`
- Push / Nimbus / per‑profile identifiers

### Timestamps and lifecycle state
Examples:
- `last*`, `next*`, `*_date`, `*_time`, `*_seconds`
- `privacy.purge_trackers.last_purge`
- `browser.startup.lastColdStartupCheck`

### Counters and history
Examples:
- `browser.search.totalSearches`
- `*count`, `*counter`, `*impressions`

### Migration, UI, and bookkeeping state
Examples:
- `*.has-used`, `*.ever*`, `*.seen`, `*.pending`
- `browser.uiCustomization.state`
- `browser.pageActions.persistedActions`
- `extensions.*Schema`, `*migration*`

### Component / DRM / hardware bookkeeping
Examples:
- `media.gmp-*`
- `gfx.blacklist.*`
- temp directory suffixes, failure IDs, hashes

These are **not configuration** and pinning them is harmful.

---

## Output behavior

- Reads from the active LibreWolf profile’s `prefs.js`
- Writes enforced settings to `librewolf.overrides.cfg`
- Uses `pref(...)` (hard enforcement), not `defaultPref(...)`
- Supports full auditing of skipped preferences

Useful commands:

```bash
python3 lw_export_overrides_policyonly.py
python3 lw_export_overrides_policyonly.py --print-skipped
python3 lw_export_overrides_policyonly.py --stats
```

---

## License

GPL‑3.0‑only. See `LICENSE`.
