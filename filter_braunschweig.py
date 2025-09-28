#!/usr/bin/env python3
# filter_braunschweig.py
import requests
import os
import sys
import logging
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
    try:
        r = requests.get(URL, headers=headers, timeout=30)
    except Exception as e:
        logging.error("HTTP request failed: %s", e)
        raise
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


def filter_calendar(ics_text):
    try:
        cal = Calendar(ics_text)
    except Exception as e:
        logging.error("Failed to parse input calendar: %s", e)
        raise
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
            # clean the summary/title if present
            try:
                ev.name = clean_summary(getattr(ev, "name", None))
            except Exception:
                # defensive: if setting name fails, skip cleaning
                pass
            out.events.add(ev)
            matched += 1
    logging.info("Matched events: %d", matched)
    return out


def write_output(cal):
    try:
        with open(OUT_FILE, "w", encoding="utf-8") as f:
            f.writelines(cal)
    except Exception as e:
        logging.error("Failed to write output file: %s", e)
        raise


def main():
    try:
        ics_text, new_meta = fetch()
        logging.info("Fetched feed: %s", "None" if ics_text is None else f"{len(ics_text)} bytes")
        if ics_text is None:
            logging.info("No update needed. Exiting.")
            return 0
        out_cal = filter_calendar(ics_text)
        logging.info("Writing output file: %s", OUT_FILE)
        write_output(out_cal)
        save_meta(new_meta)
        logging.info("Wrote %s with %d events.", OUT_FILE, len(out_cal.events))
        return 0
    except Exception as e:
        logging.error("Error in main: %s", e)
        return 2


if __name__ == "__main__":
    sys.exit(main())
