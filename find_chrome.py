#!/usr/bin/env python3
"""Find Chrome binary and profile directories on macOS, Windows, and Linux."""

import os
import platform
import json
import sys


def find_chrome_binary():
    """Return list of Chrome binary paths found on this system."""
    system = platform.system()
    candidates = []

    if system == "Darwin":
        candidates = [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            os.path.expanduser("~/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
            "/Applications/Google Chrome Canary.app/Contents/MacOS/Google Chrome Canary",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
        ]
    elif system == "Windows":
        for env_var in ["PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"]:
            base = os.environ.get(env_var, "")
            if base:
                candidates.append(os.path.join(base, "Google", "Chrome", "Application", "chrome.exe"))
        candidates.append(os.path.expanduser(r"~\AppData\Local\Google\Chrome\Application\chrome.exe"))
    else:  # Linux
        candidates = [
            "/usr/bin/google-chrome",
            "/usr/bin/google-chrome-stable",
            "/usr/bin/chromium",
            "/usr/bin/chromium-browser",
            "/snap/bin/chromium",
        ]

    return [c for c in candidates if os.path.isfile(c)]


def find_chrome_profiles():
    """Return the user-data-dir and list of profile directories."""
    system = platform.system()

    if system == "Darwin":
        user_data_dir = os.path.expanduser("~/Library/Application Support/Google/Chrome")
    elif system == "Windows":
        user_data_dir = os.path.expanduser(r"~\AppData\Local\Google\Chrome\User Data")
    else:
        user_data_dir = os.path.expanduser("~/.config/google-chrome")

    if not os.path.isdir(user_data_dir):
        return user_data_dir, []

    profiles = []

    # "Default" profile
    default_prefs = os.path.join(user_data_dir, "Default", "Preferences")
    if os.path.isdir(os.path.join(user_data_dir, "Default")):
        name = _read_profile_name(default_prefs)
        profiles.append({"dir": "Default", "name": name})

    # "Profile N" directories
    for entry in sorted(os.listdir(user_data_dir)):
        if entry.startswith("Profile ") and os.path.isdir(os.path.join(user_data_dir, entry)):
            prefs_path = os.path.join(user_data_dir, entry, "Preferences")
            name = _read_profile_name(prefs_path)
            profiles.append({"dir": entry, "name": name})

    return user_data_dir, profiles


def _read_profile_name(prefs_path):
    """Read the human-readable profile name from Chrome's Preferences JSON."""
    try:
        with open(prefs_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("profile", {}).get("name", "(unknown)")
    except Exception:
        return "(unknown)"


def main():
    print(f"System: {platform.system()} {platform.machine()}\n")

    # --- Chrome binary ---
    binaries = find_chrome_binary()
    if binaries:
        print("Chrome binary found:")
        for b in binaries:
            print(f"  {b}")
        print()
        # Show launch command for remote debugging
        binary = binaries[0]
        if platform.system() == "Darwin":
            escaped = binary.replace(" ", r"\ ")
            print("To launch with remote debugging:")
            print(f"  {escaped} --remote-debugging-port=9222\n")
        elif platform.system() == "Windows":
            print("To launch with remote debugging:")
            print(f'  "{binary}" --remote-debugging-port=9222\n')
        else:
            print("To launch with remote debugging:")
            print(f"  {binary} --remote-debugging-port=9222\n")
    else:
        print("Chrome binary: NOT FOUND\n")

    # --- Profiles ---
    user_data_dir, profiles = find_chrome_profiles()
    if profiles:
        print(f"Chrome user-data-dir:\n  {user_data_dir}\n")
        print("Profiles found:")
        for p in profiles:
            print(f"  {p['dir']:20s}  ({p['name']})")
        print()

        # Show example commands
        print("=" * 60)
        print("Example commands:")
        print("=" * 60)
        prof = profiles[0]
        print(f'\n  # Using your Chrome profile (close Chrome first):')
        print(f'  python rebelsavings.py --chrome-profile "{user_data_dir}" --profile-dir "{prof["dir"]}"')
        print(f'  python fb_scraper.py --chrome-profile "{user_data_dir}" --profile-dir "{prof["dir"]}"')
        print(f'\n  # Using remote debugging (Chrome stays open):')
        if platform.system() == "Darwin":
            escaped = binaries[0].replace(" ", r"\ ") if binaries else "google-chrome"
            print(f"  {escaped} --remote-debugging-port=9222")
        else:
            print(f'  "{binaries[0] if binaries else "chrome"}" --remote-debugging-port=9222')
        print(f"  python rebelsavings.py --remote-debug localhost:9222")
        print(f"  python fb_scraper.py --remote-debug localhost:9222")
        print()
    else:
        print(f"Chrome profiles: NOT FOUND (looked in {user_data_dir})\n")


if __name__ == "__main__":
    main()
