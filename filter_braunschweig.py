#!/usr/bin/env python3
# filter_braunschweig.py
import requests
import os
import sys
import logging
import tempfile
from ics import Calendar

# --- Konfiguration ---
URL = "http://api.basketball-bundesliga.de/calendar/ical/all-games"
TEAM_VARIANTS = [
    "Löwen Braunschweig",
    "Loewen Braunschweig",
    "Braunschweig",
    "Basketball Löwen",
]
OUT_FILE = "loewen_braunschweig.ics"
BAK_FILE = OUT_FILE + ".bak"   # deine _temp.ics (Sicherung der alten Datei)
NEW_FILE = OUT_FILE + ".new"   # temporäre neue Datei während Generierung
META_FILE = ".feedmeta"  # speichert ETag / Last-Modified
REMOVE_PREFIXES = [
    "easyCredit BBL Spiel ",
]
# ----------------------

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


def load_meta():
    if not os.path.exists(META_FILE):
        return {}
    try:
        with open(META_FILE, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()
        meta = {}
        for line in lines:
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip()] = v.strip()
        return meta
    except Exception as e:
        logging.warning("Could not read meta: %s", e)
        return {}


def save_meta(meta):
    try:
        with open(META_FILE, "w", encoding="utf-8") as f:
            for k, v in meta.items():
                f.write(f"{k}:{v}\n")
    except Exception as e:
        logging.warning("Could not write meta: %s", e)


def fetch():
    headers = {}
    meta = load_meta()
    if "ETag" in meta:
        headers["If-None-Match"] = meta["ETag"]
    if "Last-Modified" in meta:
        headers["If-Modified-Since"] = meta["Last-Modified"]
    logging.info("Requesting feed...")
    r = requests.get(URL, headers=headers, timeout=30)
    if r.status_code == 304:
        logging.info("Feed not modified (304).")
        return None, meta
    r.raise_for_status()
    new_meta = {}
    if "ETag" in r.headers:
        new_meta["ETag"] = r.headers["ETag"]
    if "Last-Modified" in r.headers:
        new_meta["Last-Modified"] = r.headers["Last-Modified"]
    return r.text, new_meta


def matches_team(text):
    txt = (text or "").lower()
    for v in TEAM_VARIANTS:
        if v.lower() in txt:
            return True
    return False


def clean_summary(name):
    if not name:
        return name
    n = name.strip()
    ln = n.lower()
    for p in REMOVE_PREFIXES:
        if ln.startswith(p.lower()):
            n = n[len(p):].lstrip()
            break
    return n


def filter_calendar_to_string(ics_text):
    cal = Calendar(ics_text)
    out = Calendar()
    matched = 0
    for ev in cal.events:
        combined = " ".join(
            filter(
                None,
                [
                    getattr(ev, "name", ""),
                    getattr(ev, "description", ""),
                    getattr(ev, "location", ""),
                ],
            )
        )
        if matches_team(combined):
            try:
                ev.name = clean_summary(getattr(ev, "name", None))
            except Exception:
                pass
            out.events.add(ev)
            matched += 1
    logging.info("Matched events: %d", matched)
    return str(out), matched


def atomic_replace_with_backup(new_text):
    """
    Safe replace strategy:
    - If OUT_FILE exists, rename it to BAK_FILE.
    - Write NEW_FILE with new_text.
    - If write successful, rename NEW_FILE -> OUT_FILE and remove BAK_FILE.
    - On failure, remove NEW_FILE and restore BAK_FILE -> OUT_FILE.
    """
    try:
        # make backup if exists
        if os.path.exists(OUT_FILE):
            # remove old bak if present to avoid conflicts
            if os.path.exists(BAK_FILE):
                os.remove(BAK_FILE)
            os.replace(OUT_FILE, BAK_FILE)
            logging.info("Existing %s moved to backup %s", OUT_FILE, BAK_FILE)

        # write new content to NEW_FILE
        with open(NEW_FILE, "w", encoding="utf-8") as f:
            f.write(new_text)
        logging.info("Wrote new temp file %s", NEW_FILE)

        # replace: NEW_FILE -> OUT_FILE
        os.replace(NEW_FILE, OUT_FILE)
        logging.info("Replaced %s with new file", OUT_FILE)

        # remove backup
        if os.path.exists(BAK_FILE):
            os.remove(BAK_FILE)
            logging.info("Removed backup %s", BAK_FILE)
        return True
    except Exception as e:
        logging.error("Error during atomic replace: %s", e)
        # cleanup new file if present
        try:
            if os.path.exists(NEW_FILE):
                os.remove(NEW_FILE)
                logging.info("Removed failed new file %s", NEW_FILE)
        except Exception:
            pass
        # restore backup if exists
        try:
            if os.path.exists(BAK_FILE):
                # if OUT_FILE exists for some reason, remove it first
                if os.path.exists(OUT_FILE):
                    os.remove(OUT_FILE)
                os.replace(BAK_FILE, OUT_FILE)
                logging.info("Restored backup %s to %s", BAK_FILE, OUT_FILE)
        except Exception as e2:
            logging.error("Failed to restore backup: %s", e2)
        return False


def main():
    try:
        ics_text, new_meta = fetch()
        logging.info("Fetched feed: %s", "None" if ics_text is None else f"{len(ics_text)} bytes")
        if ics_text is None:
            logging.info("No update needed. Exiting.")
            return 0

        new_text, matched = filter_calendar_to_string(ics_text)
        # If you want to avoid empty output, you can decide here:
        # if matched == 0: ... (we proceed and write empty calendar)
        logging.info("Preparing atomic replace of %s", OUT_FILE)
        ok = atomic_replace_with_backup(new_text)
        if ok:
            save_meta(new_meta)
            logging.info("Update successful. Wrote %s with %d events.", OUT_FILE, matched)
            return 0
        else:
            logging.error("Update failed; backup restored.")
            return 2
    except Exception as e:
        logging.error("Fatal error: %s", e)
        # Attempt to restore backup if something unexpected happened
        try:
            if os.path.exists(BAK_FILE) and not os.path.exists(OUT_FILE):
                os.replace(BAK_FILE, OUT_FILE)
                logging.info("Restored backup after fatal error.")
        except Exception as e2:
            logging.error("Failed to restore backup after fatal error: %s", e2)
        return 2


if __name__ == "__main__":
    sys.exit(main())
