#!/usr/bin/env python3
# filter_braunschweig.py
import requests
import os
import sys
import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
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
BAK_FILE = OUT_FILE + ".bak"
NEW_FILE = OUT_FILE + ".new"
META_FILE = ".feedmeta"
REMOVE_PREFIXES = [
    "easyCredit BBL Spiel ",
]
TZID = "Europe/Berlin"
# ----------------------

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
LOCAL_TZ = ZoneInfo(TZID)


VTIMEZONE_BLOCK = """BEGIN:VTIMEZONE
TZID:{tz}
X-LIC-LOCATION:{tz}
BEGIN:STANDARD
TZOFFSETFROM:+0200
TZOFFSETTO:+0100
TZNAME:CET
DTSTART:19701025T030000
END:STANDARD
BEGIN:DAYLIGHT
TZOFFSETFROM:+0100
TZOFFSETTO:+0200
TZNAME:CEST
DTSTART:19700329T020000
END:DAYLIGHT
END:VTIMEZONE
""".format(tz=TZID)


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
                if v is not None and v != "":
                    f.write(f"{k}:{v}\n")
    except Exception as e:
        logging.warning("Could not write meta: %s", e)


def fetch():
    headers = {}
    meta = load_meta()
    if meta.get("ETag"):
        headers["If-None-Match"] = meta["ETag"]
    if meta.get("Last-Modified"):
        headers["If-Modified-Since"] = meta["Last-Modified"]
    logging.info("Requesting feed... headers=%s", headers)
    r = requests.get(URL, headers=headers, timeout=30)
    logging.info("HTTP %s received", r.status_code)
    if r.status_code == 304:
        logging.info("Feed not modified (304).")
        return None, meta
    r.raise_for_status()
    new_meta = {}
    if r.headers.get("ETag"):
        new_meta["ETag"] = r.headers.get("ETag")
    if r.headers.get("Last-Modified"):
        new_meta["Last-Modified"] = r.headers.get("Last-Modified")
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


def ensure_datetime(obj):
    """
    Return a datetime (naive or aware) from various ics types or datetime.
    """
    if obj is None:
        return None
    try:
        if hasattr(obj, "naive"):
            return obj.naive  # naive datetime
        if hasattr(obj, "datetime"):
            return obj.datetime  # possibly aware
    except Exception:
        pass
    return obj


def wallclock_as_local_naive(dt):
    """
    Interpret the wall-clock time of dt as Europe/Berlin local time and return naive local datetime.
    Rules:
      - If dt is aware (has tzinfo), take its wall-clock components (year,month,day,hour,minute,second)
        and build a LOCAL_TZ-aware datetime with those components, then return naive local datetime.
      - If dt is naive, take its components as-is and treat them as LOCAL_TZ local time.
    This preserves the displayed clock time while writing TZID=Europe/Berlin.
    """
    if dt is None:
        return None
    py_dt = ensure_datetime(dt)
    if py_dt is None:
        return None
    # Extract wall-clock fields
    wc = dict(year=py_dt.year, month=py_dt.month, day=py_dt.day,
              hour=py_dt.hour, minute=py_dt.minute, second=py_dt.second, microsecond=py_dt.microsecond)
    # create a local-aware datetime using those fields
    local_aware = datetime(**wc, tzinfo=LOCAL_TZ)
    # return naive local (no tzinfo) for ICS writing with TZID
    return local_aware.replace(tzinfo=None)


def format_dt_as_local_string(dt):
    return dt.strftime("%Y%m%dT%H%M%S")


def escape_ical_text(s):
    return s.replace("\\", "\\\\").replace("\n", "\\n").replace(",", "\\,").replace(";", "\\;")


def build_ics_text_with_vtimezone(cal_out):
    lines = []
    lines.append("BEGIN:VCALENDAR")
    lines.append("VERSION:2.0")
    lines.append("PRODID:-//Filtered Calendar//EN")
    lines.append(VTIMEZONE_BLOCK.strip())
    for ev in cal_out.events:
        lines.append("BEGIN:VEVENT")
        uid = getattr(ev, "uid", None) or ""
        if uid:
            lines.append(f"UID:{uid}")
        summary = getattr(ev, "name", "") or ""
        lines.append(f"SUMMARY:{escape_ical_text(summary)}")
        desc = getattr(ev, "description", "") or ""
        if desc:
            lines.append(f"DESCRIPTION:{escape_ical_text(desc)}")
        loc = getattr(ev, "location", "") or ""
        if loc:
            lines.append(f"LOCATION:{escape_ical_text(loc)}")

        # BEGIN/END times: preserve wall-clock time and write TZID=Europe/Berlin
        b = getattr(ev, "begin", None)
        e = getattr(ev, "end", None)
        b_dt = ensure_datetime(b)
        e_dt = ensure_datetime(e)

        b_local_naive = wallclock_as_local_naive(b_dt) if b_dt is not None else None
        e_local_naive = wallclock_as_local_naive(e_dt) if e_dt is not None else None

        if b_local_naive:
            lines.append(f"DTSTART;TZID={TZID}:{format_dt_as_local_string(b_local_naive)}")
        if e_local_naive:
            lines.append(f"DTEND;TZID={TZID}:{format_dt_as_local_string(e_local_naive)}")

        # CREATED/DTSTAMP remain UTC if possible
        created = getattr(ev, "created", None)
        if created:
            try:
                c_dt = ensure_datetime(created)
                if getattr(c_dt, "tzinfo", None) is None:
                    c_aware = c_dt.replace(tzinfo=timezone.utc)
                else:
                    c_aware = c_dt
                lines.append(f"CREATED:{c_aware.astimezone(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}")
            except Exception:
                pass

        lines.append(f"DTSTAMP:{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}")

        if not uid:
            key = (summary + (format_dt_as_local_string(b_local_naive) if b_local_naive else "")).encode("utf-8")
            import hashlib
            uid_gen = hashlib.sha1(key).hexdigest() + "@generated"
            lines.append(f"UID:{uid_gen}")

        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


def filter_calendar_to_string_with_tz(ics_text):
    cal = Calendar(ics_text)
    out = Calendar()
    matched = 0
    for ev in cal.events:
        combined = " ".join(filter(None, [getattr(ev, "name", ""), getattr(ev, "description", ""), getattr(ev, "location", "")]))
        if matches_team(combined):
            try:
                ev.name = clean_summary(getattr(ev, "name", None))
            except Exception:
                pass
            out.events.add(ev)
            matched += 1
    text = build_ics_text_with_vtimezone(out)
    return text, matched


def atomic_replace_with_backup(new_text):
    try:
        if os.path.exists(OUT_FILE):
            if os.path.exists(BAK_FILE):
                os.remove(BAK_FILE)
            os.replace(OUT_FILE, BAK_FILE)
            logging.info("Existing %s moved to backup %s", OUT_FILE, BAK_FILE)
        with open(NEW_FILE, "w", encoding="utf-8") as f:
            f.write(new_text)
        logging.info("Wrote new temp file %s", NEW_FILE)
        os.replace(NEW_FILE, OUT_FILE)
        logging.info("Replaced %s with new file", OUT_FILE)
        if os.path.exists(BAK_FILE):
            os.remove(BAK_FILE)
            logging.info("Removed backup %s", BAK_FILE)
        return True
    except Exception as e:
        logging.error("Error during atomic replace: %s", e)
        try:
            if os.path.exists(NEW_FILE):
                os.remove(NEW_FILE)
        except Exception:
            pass
        try:
            if os.path.exists(BAK_FILE):
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
            if not os.path.exists(OUT_FILE):
                logging.info("No existing output file but feed reported 304/None — forcing fresh fetch without conditional headers.")
                r = requests.get(URL, timeout=30)
                r.raise_for_status()
                ics_text = r.text
                new_meta = {}
                if r.headers.get("ETag"):
                    new_meta["ETag"] = r.headers.get("ETag")
                if r.headers.get("Last-Modified"):
                    new_meta["Last-Modified"] = r.headers.get("Last-Modified")
            else:
                logging.info("No update needed. Exiting.")
                return 0
        new_text, matched = filter_calendar_to_string_with_tz(ics_text)
        logging.info("Found %d matching events", matched)
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
        try:
            if os.path.exists(BAK_FILE) and not os.path.exists(OUT_FILE):
                os.replace(BAK_FILE, OUT_FILE)
                logging.info("Restored backup after fatal error.")
        except Exception as e2:
            logging.error("Failed to restore backup after fatal error: %s", e2)
        return 2


if __name__ == "__main__":
    sys.exit(main())
