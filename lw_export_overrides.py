#!/usr/bin/env python3
from __future__ import annotations

import argparse
import configparser
import re
from pathlib import Path
from typing import Iterable, Tuple, Optional, List

PREF_RE = re.compile(r'^\s*user_pref\("(?P<name>[^"]+)",\s*(?P<value>.+?)\s*\);\s*$')

# Privacy-first exporter:
# - Goal: export only *policy* prefs (stable, intentional settings).
# - Exclude: identifiers, timestamps/state, counters/history, migration/UI bookkeeping, and other churn.
# - Keep: EME/DRM toggle (media.eme.enabled) if user set it, and bookmarks auto-export path (browser.bookmarks.file)
#        if user set it (per user request).

# Namespace/prefix churn that should never be pinned
DEFAULT_EXCLUDE_PREFIXES = [
    "browser.sessionstore.",
    "browser.startup.",
    "browser.engagement.",
    "browser.migration.",
    "browser.protections_panel.",
    "browser.termsofuse.",
    "devtools.",
    "services.settings.",
    "browser.region.",
    "network.captive-portal-service.",
    "network.connectivity-service.",
    "browser.safebrowsing.provider.",  # provider update scheduling state often lives here
    "extensions.webextensions.ExtensionStorageIDB.migrated.",
    "toolkit.telemetry.cached",
    "datareporting.dau.cached",
    "nimbus.",
    "dom.push.",
]

# Case-insensitive substrings that indicate churn/state/identity (not policy)
DEFAULT_EXCLUDE_SUBSTRINGS = [
    # Identifiers / per-profile markers
    "impressionid",
    "storeid",
    "profileid",
    "clientid",
    "userid",
    "pushid",
    "installationid",
    "instanceid",
    "deviceid",
    "machineid",
    "guid",

    # Time/state/counters/history
    "last",
    "next",
    "date",
    "time",
    "seconds",
    "count",
    "counter",
    "etag",
    "skew",
    "pending",
    "qualified",

    # Migration/UX bookkeeping
    "migrat",   # migrated/migration
    "version",
    "schema",
    "checkpoint",
    "has-used",
    "ever",
    "seen",
    "shown",
    "mostrecent",

    # Known state blobs / potentially fingerprinty or revealing prefs
    "persistedactions",
    "uicustomization",
    "resultgroups",
    "quarantineddomains",
    "tempdirsuffix",
    "blacklist.",
    "failureid",
    "hashvalue",
    "buildid",
]

# Explicit regex excludes for known offenders that should never be pinned
DEFAULT_EXCLUDE_REGEXES = [
    r"^privacy\.purge_trackers\.(last_purge|date_in_cookie_database)$",
    r"^privacy\.sanitize\.pending$",
    r"^browser\.search\.totalSearches$",
    r"^browser\.pageActions\.persistedActions$",
    r"^browser\.uiCustomization\.state$",
    r"^browser\.urlbar\.resultGroups$",
    r"^extensions\.quarantinedDomains\.list$",
    r"^security\.sandbox\.content\.tempDirSuffix$",
    r"^gfx\.blacklist\.",
    r"^media\.gmp-",
    # printer prefs can embed identifying device names
    r"^print\.printer_",
    r"^print\.printer\.",
    r"^print_printer$",
]

# Explicit allowlist: keep these even if they would otherwise match a substring rule.
# Keep this tight: allow only "what should the browser do?" policy knobs.
DEFAULT_INCLUDE_REGEXES = [
    # User-requested keepers
    r"^media\.eme\.enabled$",
    r"^browser\.bookmarks\.file$",

    # Privacy posture / blocking policy
    r"^beacon\.enabled$",
    r"^network\.trr\.",
    r"^network\.dns\.",
    r"^browser\.contentblocking\.",
    r"^privacy\.trackingprotection\.",
    r"^privacy\.globalprivacycontrol\.(enabled|pbmode)$",
    r"^privacy\.resistFingerprinting$",
    r"^privacy\.partition\.",
    r"^privacy\.firstparty\.isolate$",
    r"^privacy\.query_stripping\.",
    r"^privacy\.userContext\.",

    # Form autofill policy (KeePassXC unaffected)
    r"^dom\.forms\.autocomplete\.formautofill$",

    # Telemetry/reporting posture (policy, not cached IDs)
    r"^toolkit\.telemetry\.(enabled|unified|server)$",
    r"^toolkit\.telemetry\.archive\.enabled$",
    r"^toolkit\.telemetry\.reportingpolicy\.",
    r"^datareporting\.healthreport\.",
    r"^datareporting\.policy\.",

    # Safebrowsing policy toggles (not provider update schedule state)
    r"^browser\.safebrowsing\.(downloads\.remote\.enabled|downloads\.remote\.url|malware\.enabled|phishing\.enabled)$",

    # Security posture
    r"^dom\.security\.",
    r"^security\.",
]


def candidate_base_dirs() -> List[Path]:
    home = Path.home()
    return [
        home / ".librewolf",
        home / ".var" / "app" / "io.gitlab.librewolf-community" / ".librewolf",
    ]


def read_profiles_ini(base_dir: Path) -> configparser.ConfigParser:
    ini_path = base_dir / "profiles.ini"
    if not ini_path.is_file():
        raise FileNotFoundError(f"profiles.ini not found at: {ini_path}")
    cp = configparser.ConfigParser(interpolation=None)
    cp.read(ini_path, encoding="utf-8")
    return cp


def resolve_profile_dir(base_dir: Path, cp: configparser.ConfigParser, section: str) -> Optional[Path]:
    p = cp.get(section, "Path", fallback=None)
    if not p:
        return None
    is_rel = cp.get(section, "IsRelative", fallback="1") == "1"
    return (base_dir / p) if is_rel else Path(p)


def pick_default_profile_dir(base_dir: Path) -> Path:
    cp = read_profiles_ini(base_dir)
    profiles = [s for s in cp.sections() if s.lower().startswith("profile")]
    if not profiles:
        raise RuntimeError(f"No [Profile*] sections in {base_dir}/profiles.ini")
    profiles.sort(key=lambda s: 0 if cp.get(s, "Default", fallback="0") == "1" else 1)
    for sec in profiles:
        p = resolve_profile_dir(base_dir, cp, sec)
        if p and (p / "prefs.js").is_file():
            return p
    raise RuntimeError(f"No usable profile with prefs.js under {base_dir}")


def autodetect_base_dir() -> Path:
    valid: List[Path] = []
    for bd in candidate_base_dirs():
        try:
            if (bd / "profiles.ini").is_file():
                prof = pick_default_profile_dir(bd)
                if (prof / "prefs.js").is_file():
                    valid.append(bd)
        except Exception:
            pass
    if not valid:
        return Path.home() / ".librewolf"
    non_flatpak = Path.home() / ".librewolf"
    return non_flatpak if non_flatpak in valid else valid[0]


def iter_user_prefs(prefs_js: Path) -> Iterable[Tuple[str, str]]:
    with prefs_js.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            m = PREF_RE.match(line)
            if m:
                yield m.group("name"), m.group("value")


def compile_regexes(patterns: List[str]) -> List[re.Pattern]:
    return [re.compile(p) for p in patterns]


def should_exclude(
    name: str,
    exclude_prefixes: List[str],
    exclude_substrings: List[str],
    exclude_regexes: List[re.Pattern],
    include_regexes: List[re.Pattern],
) -> bool:
    # Allowlist wins
    if any(r.search(name) for r in include_regexes):
        return False

    # Explicit regex excludes
    if any(r.search(name) for r in exclude_regexes):
        return True

    # Prefix excludes
    if any(name.startswith(p) for p in exclude_prefixes):
        return True

    # Substring churn/state/identity excludes
    n = name.lower()
    if any(s in n for s in exclude_substrings):
        return True

    return False


def write_overrides(prefs: Iterable[Tuple[str, str]], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    header = (
        "/**\n"
        " * Generated from prefs.js user preferences\n"
        " * Policy-only, privacy-first defaults:\n"
        " *  - excludes identifiers, timestamps/state, counters/history, migration/UI bookkeeping\n"
        " *  - keeps user-requested: media.eme.enabled, browser.bookmarks.file (if present)\n"
        " * Enforces values via pref().\n"
        " */"
    )
    with out_path.open("w", encoding="utf-8", newline="\n") as f:
        f.write(header.rstrip() + "\n\n")
        for name, value in prefs:
            f.write(f'pref("{name}", {value});\n')


def main() -> int:
    ap = argparse.ArgumentParser(description="Export LibreWolf policy prefs to librewolf.overrides.cfg (privacy-first)")
    ap.add_argument("--base-dir", type=Path, help="LibreWolf base dir containing profiles.ini")
    ap.add_argument("--profile-dir", type=Path, help="Explicit profile dir (overrides profiles.ini)")
    ap.add_argument("--output", type=Path, help="Output overrides file path")

    # Escape hatches
    ap.add_argument("--exclude-prefix", action="append", default=[], help="Exclude pref prefix (repeatable)")
    ap.add_argument("--exclude-substring", action="append", default=[], help="Exclude pref substring (repeatable; case-insensitive)")
    ap.add_argument("--exclude-regex", action="append", default=[], help="Exclude pref regex (repeatable)")
    ap.add_argument("--include-regex", action="append", default=[], help="Force include regex (repeatable)")

    ap.add_argument("--stats", action="store_true", help="Print include/exclude statistics")
    ap.add_argument("--print-skipped", action="store_true", help="Print skipped prefs for audit (commented user_pref lines)")
    args = ap.parse_args()

    base_dir = args.base_dir or autodetect_base_dir()
    profile_dir = args.profile_dir or pick_default_profile_dir(base_dir)
    prefs_js = profile_dir / "prefs.js"
    if not prefs_js.is_file():
        raise FileNotFoundError(f"prefs.js not found at: {prefs_js}")

    out_path = args.output or (base_dir / "librewolf.overrides.cfg")

    exclude_prefixes = DEFAULT_EXCLUDE_PREFIXES + args.exclude_prefix
    exclude_substrings = [s.lower() for s in (DEFAULT_EXCLUDE_SUBSTRINGS + args.exclude_substring)]
    exclude_regexes = compile_regexes(DEFAULT_EXCLUDE_REGEXES + args.exclude_regex)
    include_regexes = compile_regexes(DEFAULT_INCLUDE_REGEXES + args.include_regex)

    kept: List[Tuple[str, str]] = []
    dropped: List[Tuple[str, str]] = []

    for name, value in iter_user_prefs(prefs_js):
        if should_exclude(name, exclude_prefixes, exclude_substrings, exclude_regexes, include_regexes):
            dropped.append((name, value))
        else:
            kept.append((name, value))

    write_overrides(kept, out_path)

    print(f"Profile:  {profile_dir}")
    print(f"Read:     {len(kept) + len(dropped)} prefs")
    print(f"Written:  {len(kept)} prefs")
    print(f"Skipped:  {len(dropped)} prefs")
    print(f"Output:   {out_path}")

    if args.stats:
        print("\nExcluded prefixes:")
        for p in exclude_prefixes:
            print(f"  {p}")
        print("\nExcluded substrings (case-insensitive):")
        for s in exclude_substrings:
            print(f"  {s}")
        print("\nExcluded regexes:")
        for r in (DEFAULT_EXCLUDE_REGEXES + args.exclude_regex):
            print(f"  {r}")
        print("\nIncluded allowlist regexes:")
        for r in (DEFAULT_INCLUDE_REGEXES + args.include_regex):
            print(f"  {r}")

    if args.print_skipped:
        print("\n# --- skipped prefs (audit only; not enforced) ---")
        for name, value in dropped:
            print(f'# user_pref("{name}", {value});')

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
