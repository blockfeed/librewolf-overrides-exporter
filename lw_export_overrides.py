#!/usr/bin/env python3
from __future__ import annotations

import argparse
import configparser
import re
from pathlib import Path
from typing import Iterable, Tuple, Optional, List

PREF_RE = re.compile(r'^\s*user_pref\("(?P<name>[^"]+)",\s*(?P<value>.+?)\s*\);\s*$')

# Privacy-aligned defaults:
# - Export and enforce user-changed privacy *settings*.
# - Skip only volatile/session prefs and identifier/cache churn that should not be "pinned" in policy.
DEFAULT_EXCLUDE_PREFIXES = [
    # Volatile session/runtime state
    "browser.sessionstore.",

    # Extension/profile churn and bookkeeping (not stable policy)
    "extensions.webextensions.uuids",
    "extensions.lastAppBuildId",
    "extensions.lastPlatformVersion",
    "extensions.databaseSchema",

    # Identifier/cache churn (avoid pinning IDs in overrides)
    "toolkit.telemetry.cached",
    "datareporting.dau.cached",
]


# ---------- profile / base dir detection ----------

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

    # Prefer Default=1, else first profile
    profiles.sort(key=lambda s: 0 if cp.get(s, "Default", fallback="0") == "1" else 1)

    # Prefer a profile that actually has prefs.js
    for sec in profiles:
        p = resolve_profile_dir(base_dir, cp, sec)
        if p and (p / "prefs.js").is_file():
            return p

    raise RuntimeError(f"No usable profile with prefs.js under {base_dir}")


def autodetect_base_dir() -> Path:
    """
    Choose the base dir (Flatpak or non-Flatpak) whose profiles.ini resolves to an existing prefs.js.
    Prefer non-Flatpak if both are valid.
    """
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
        # Likely non-Flatpak; caller will error clearly if wrong
        return Path.home() / ".librewolf"

    non_flatpak = Path.home() / ".librewolf"
    return non_flatpak if non_flatpak in valid else valid[0]


# ---------- prefs handling ----------

def iter_user_prefs(prefs_js: Path) -> Iterable[Tuple[str, str]]:
    with prefs_js.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            m = PREF_RE.match(line)
            if m:
                yield m.group("name"), m.group("value")


def should_exclude(
    name: str,
    exclude_prefixes: List[str],
    exclude_regexes: List[re.Pattern],
    include_regexes: List[re.Pattern],
) -> bool:
    # Explicit include wins
    if any(r.search(name) for r in include_regexes):
        return False
    if any(name.startswith(p) for p in exclude_prefixes):
        return True
    if any(r.search(name) for r in exclude_regexes):
        return True
    return False


def write_overrides(prefs: Iterable[Tuple[str, str]], out_path: Path, header: str) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="\n") as f:
        f.write(header.rstrip() + "\n\n")
        for name, value in prefs:
            f.write(f'pref("{name}", {value});\n')


# ---------- main ----------

def main() -> int:
    ap = argparse.ArgumentParser(
        description="Export LibreWolf modified prefs (prefs.js user_pref entries) to librewolf.overrides.cfg"
    )
    ap.add_argument("--base-dir", type=Path, help="LibreWolf base dir containing profiles.ini")
    ap.add_argument("--profile-dir", type=Path, help="Explicit profile dir (overrides profiles.ini)")
    ap.add_argument("--output", type=Path, help="Output overrides file path")
    ap.add_argument("--exclude-prefix", action="append", default=[], help="Exclude pref prefix (repeatable)")
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
    exclude_regexes = [re.compile(r) for r in args.exclude_regex]
    include_regexes = [re.compile(r) for r in args.include_regex]

    kept: List[Tuple[str, str]] = []
    dropped: List[Tuple[str, str]] = []

    for name, value in iter_user_prefs(prefs_js):
        if should_exclude(name, exclude_prefixes, exclude_regexes, include_regexes):
            dropped.append((name, value))
        else:
            kept.append((name, value))

    header = (
        "/**\n"
        " * Generated from prefs.js user preferences\n"
        " * Privacy-aligned: exports privacy settings; skips volatile/session + identifier/cache churn\n"
        " * This file enforces values via pref()\n"
        " */"
    )

    write_overrides(kept, out_path, header)

    print(f"Profile:  {profile_dir}")
    print(f"Read:     {len(kept) + len(dropped)} prefs")
    print(f"Written:  {len(kept)} prefs")
    print(f"Skipped:  {len(dropped)} prefs")
    print(f"Output:   {out_path}")

    if args.stats:
        print("\nSkipped prefixes:")
        for p in exclude_prefixes:
            print(f"  {p}")

    if args.print_skipped:
        print("\n# --- skipped prefs (audit only; not enforced) ---")
        for name, value in dropped:
            print(f'# user_pref("{name}", {value});')

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
