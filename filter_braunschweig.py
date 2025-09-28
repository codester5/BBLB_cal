#!/usr/bin/env python3
# filter_braunschweig.py
import requests, os, sys, logging
from ics import Calendar

URL = "http://api.basketball-bundesliga.de/calendar/ical/all-games"
TEAM_VARIANTS = ["Löwen Braunschweig", "Loewen Braunschweig", "Braunschweig", "Basketball Löwen"]
OUT_FILE = "loewen_braunschweig.ics"
META_FILE = ".feedmeta"  # stores ETag / Last-Modified
REMOVE_PREFIX = "easyCredit BBL Spiel "

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
                k,v = line.split(":",1)
                meta[k.strip()] = v.strip()
        return meta
    except Exception as e:
        logging.warning("Could not read meta: %s", e)
        return {}

def save_meta(meta):
    try:
        with open(META_FILE, "w", encoding="utf-8") as f:
            for k,v in meta.items():
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
    if n.lower().startswith(REMOVE_PREFIX.lower()):
        n = n[len(REMOVE_PREFIX):].lstrip()
    return n

def filter_calendar(ics_text):
    cal = Calendar(ics_text)
    out = Calendar()
    for ev in cal.events:
        combined = " ".join(filter(None, [ev.name, ev.description, ev.location]))
        if matches_team(combined):
            # clean the summary/title
            ev.name = clean_summary(ev.name)
            out.events.add(ev)
    return out

def main():
    try:
        ics_text, new_meta = fetch()
        if ics_text is None:
            logging.info("No update needed. Exiting.")
            return 0
        out_cal = filter_calendar(ics_text)
        with open(OUT_FILE, "w", encoding="utf-8") as f:
            f.writelines(out_cal)
        save_meta(new_meta)
        logging.info("Wrote %s with %d events.", OUT_FILE, len(out_cal.events))
        return 0
    except Exception as e:
        logging.error("Error: %s", e)
        return 2

if __name__ == "__main__":
    sys.exit(main())
