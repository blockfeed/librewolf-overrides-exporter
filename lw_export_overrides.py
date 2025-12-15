#!/usr/bin/env python3
from __future__ import annotations

import argparse
import configparser
import re
from pathlib import Path
from typing import Iterable, Tuple, Optional, List

PREF_RE = re.compile(r'^\s*user_pref\("(?P<name>[^"]+)",\s*(?P<value>.+?)\s*\);\s*$')

# Policy-only, privacy-first exporter.
# Hard rule: explicit denylist ALWAYS wins over allowlist.

DEFAULT_EXCLUDE_PREFIXES = [
    # session/runtime churn
    "browser.sessionstore.",
    "browser.startup.",
    # UI / engagement bookkeeping
    "browser.engagement.",
    "browser.migration.",
    "browser.protections_panel.",
    "browser.termsofuse.",
    "devtools.",
    # remote settings / region / connectivity bookkeeping
    "services.settings.",
    "browser.region.",
    "network.captive-portal-service.",
    "network.connectivity-service.",
    "browser.safebrowsing.provider.",
    # distro/policy bookkeeping
    "browser.policies.",
    "distribution.",
    # extensions churn
    "extensions.getAddons.",
    "extensions.systemAddonSet",  # JSON blob state
    # telemetry/reporting caches
    "toolkit.telemetry.cached",
    "datareporting.dau.cached",
    # experiments/rollouts
    "nimbus.",
    # push identifiers/state
    "dom.push.",
    # never pin: per-profile extension UUID map
    "extensions.webextensions.uuids",
    # never pin: font fingerprinting surface
    "font.",
]

DEFAULT_EXCLUDE_SUBSTRINGS = [
    # identifiers / per-profile markers
    "impressionid", "storeid", "profileid", "clientid", "userid",
    "pushid", "installationid", "instanceid", "deviceid", "machineid", "guid", "uuid",
    # time / state / counters / history
    "last", "next", "date", "time", "seconds", "count", "counter",
    "etag", "skew", "pending", "qualified",
    # migration/UX bookkeeping
    "migrat", "version", "schema", "checkpoint", "has-used",
    "ever", "seen", "shown", "mostrecent", "applied", "processed",
    # known state blobs / revealing prefs
    "persistedactions", "uicustomization", "resultgroups",
    "quarantineddomains", "tempdirsuffix",
    "blacklist.", "failureid", "hashvalue", "buildid",
]

# Explicit denylist regexes (MUST win over allowlist)
DEFAULT_EXCLUDE_REGEXES = [
    r"^extensions\.webextensions\.uuids$",  # critical: never pin
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
    r"^print\.printer_",
    r"^print\.printer\.",
    r"^print_printer$",
]

# Allowlist regexes (tight; denylist still wins)
DEFAULT_INCLUDE_REGEXES = [
    # user-intent policy
    r"^media\.eme\.enabled$",
    r"^browser\.bookmarks\.autoExportHTML$",
    r"^browser\.bookmarks\.file$",

    # privacy / security posture
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

    # autofill policy (KeePassXC unaffected)
    r"^dom\.forms\.autocomplete\.formautofill$",

    # telemetry policy (not cached IDs)
    r"^toolkit\.telemetry\.(enabled|unified|server)$",
    r"^toolkit\.telemetry\.archive\.enabled$",
    r"^toolkit\.telemetry\.reportingpolicy\.",
    r"^datareporting\.healthreport\.",
    r"^datareporting\.policy\.",

    # safebrowsing policy toggles
    r"^browser\.safebrowsing\.(downloads\.remote\.enabled|downloads\.remote\.url|malware\.enabled|phishing\.enabled)$",

    # security policy subsets (avoid broad ^security\.)
    r"^security\.(tls\.|ssl\.|ocsp\.)",
    r"^dom\.security\.",
]


def candidate_base_dirs() -> List[Path]:
    home = Path.home()
    return [
        home / ".librewolf",
        home / ".var" / "app" / "io.gitlab.librewolf-community" / ".librewolf",
    ]


def read_profiles_ini(base_dir: Path) -> configparser.ConfigParser:
    ini = base_dir / "profiles.ini"
    if not ini.is_file():
        raise FileNotFoundError(f"profiles.ini not found at: {ini}")
    cp = configparser.ConfigParser(interpolation=None)
    cp.read(ini, encoding="utf-8")
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
    profiles.sort(key=lambda s: 0 if cp.get(s, "Default", fallback="0") == "1" else 1)
    for sec in profiles:
        p = resolve_profile_dir(base_dir, cp, sec)
        if p and (p / "prefs.js").is_file():
            return p
    raise RuntimeError("No usable profile found")


def autodetect_base_dir() -> Path:
    for bd in candidate_base_dirs():
        try:
            pick_default_profile_dir(bd)
            return bd
        except Exception:
            continue
    return Path.home() / ".librewolf"


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
    if any(r.search(name) for r in exclude_regexes):
        return True
    if any(r.search(name) for r in include_regexes):
        return False
    if any(name.startswith(p) for p in exclude_prefixes):
        return True
    n = name.lower()
    return any(s in n for s in exclude_substrings)


def write_overrides(prefs: Iterable[Tuple[str, str]], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    header = (
        "/**\n"
        " * Generated from prefs.js user preferences\n"
        " * Policy-only, privacy-first: no IDs, timestamps, counters, UI state, or font pinning\n"
        " */"
    )
    with out_path.open("w", encoding="utf-8", newline="\n") as f:
        f.write(header + "\n\n")
        for name, value in prefs:
            f.write(f'pref("{name}", {value});\n')


def main() -> int:
    ap = argparse.ArgumentParser(description="Export LibreWolf policy prefs to librewolf.overrides.cfg (privacy-first)")
    ap.add_argument("--base-dir", type=Path)
    ap.add_argument("--profile-dir", type=Path)
    ap.add_argument("--output", type=Path)
    ap.add_argument("--print-skipped", action="store_true")
    args = ap.parse_args()

    base_dir = args.base_dir or autodetect_base_dir()
    profile_dir = args.profile_dir or pick_default_profile_dir(base_dir)
    prefs_js = profile_dir / "prefs.js"
    if not prefs_js.is_file():
        raise FileNotFoundError(prefs_js)

    out_path = args.output or (base_dir / "librewolf.overrides.cfg")

    exclude_prefixes = DEFAULT_EXCLUDE_PREFIXES
    exclude_substrings = DEFAULT_EXCLUDE_SUBSTRINGS
    exclude_regexes = compile_regexes(DEFAULT_EXCLUDE_REGEXES)
    include_regexes = compile_regexes(DEFAULT_INCLUDE_REGEXES)

    kept, dropped = [], []
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

    if args.print_skipped:
        print("\n# --- skipped prefs (audit) ---")
        for n, v in dropped:
            print(f'# user_pref("{n}", {v});')

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
