#!/usr/bin/env python3
"""
PoC για το ΓΕΜΗ OpenData API.

Ροή:
  1. GET /metadata/legalTypes  -> εύρεση id για "Ιδιωτική Κεφαλαιουχική Εταιρεία (ΙΚΕ)"
  2. GET /companies            -> πρώτες 10 ενεργές ΙΚΕ (legalTypes=<id>, isActive=true)
  3. GET /companies/{arGemi}   -> πλήρη στοιχεία κάθε εταιρείας
  4. Εκτύπωση πίνακα + αποθήκευση σε test_ike_companies.csv

Επαληθευμένο από το επίσημο Swagger (https://opendata-api.businessportal.gr/api-docs):
  - host/basePath : https://opendata-api.businessportal.gr/api/opendata/v1
  - authentication: header με όνομα "api_key"
  - test key (techdocs): "api-docs-key"  (με παύλες)
"""

import csv
import os
import sys
import time
import unicodedata

import requests

# --------------------------------------------------------------------------
# Ρυθμίσεις
# --------------------------------------------------------------------------
BASE_URL = "https://opendata-api.businessportal.gr/api/opendata/v1"
API_KEY_HEADER = "api_key"        # όνομα header, όπως στο Swagger (securityDefinitions)
TEST_API_KEY = "api-docs-key"     # δημόσιο δοκιμαστικό κλειδί της τεκμηρίωσης
TARGET_LEGAL_TYPE = "Ιδιωτική Κεφαλαιουχική Εταιρεία (ΙΚΕ)"

LIMIT = 10                        # ΜΟΝΟ 10 εταιρείες - δεν κατεβάζουμε ολόκληρο το dataset
DELAY_SECONDS = 1.0               # παύση ανάμεσα στα requests
TIMEOUT_SECONDS = 30
MAX_RETRIES = 4                   # για 429 / 503 / network errors
OUTPUT_CSV = "test_ike_companies.csv"

# Προαιρετικά: μπορείς να δώσεις δικό σου κλειδί μέσω μεταβλητής περιβάλλοντος.
# Στον κώδικα υπάρχει ΜΟΝΟ το δημόσιο test key.
API_KEY = os.environ.get("GEMI_API_KEY", TEST_API_KEY)

CSV_COLUMNS = [
    "gemi_number", "afm", "name", "legal_type", "status",
    "email", "website", "address", "city_municipality", "primary_kad",
]


# --------------------------------------------------------------------------
# Εξαιρέσεις
# --------------------------------------------------------------------------
class GemiError(Exception):
    """Γενικό σφάλμα API."""


class GemiAuthError(GemiError):
    """401/403 - πρόβλημα με το api_key."""


class GemiNotFound(GemiError):
    """404 - δεν βρέθηκε εγγραφή."""


# --------------------------------------------------------------------------
# HTTP client
# --------------------------------------------------------------------------
class GemiClient:
    def __init__(self, api_key=API_KEY, delay=DELAY_SECONDS):
        self.session = requests.Session()
        self.session.headers.update({
            API_KEY_HEADER: api_key,
            "Accept": "application/json",
        })
        self.delay = delay
        self._last_request = 0.0

    def _throttle(self):
        """Εξασφαλίζει τουλάχιστον `delay` δευτερόλεπτα ανάμεσα στα requests."""
        wait = self.delay - (time.monotonic() - self._last_request)
        if wait > 0:
            time.sleep(wait)
        self._last_request = time.monotonic()

    @staticmethod
    def _error_text(resp):
        """Μορφοποίηση του ErrorEntry[] ({code, message}) του API, αν υπάρχει."""
        try:
            data = resp.json()
            if isinstance(data, list):
                return "; ".join(f"{e.get('code')}: {e.get('message')}" for e in data)
        except ValueError:
            pass
        return resp.text[:200].strip() or resp.reason

    def get(self, path, params=None):
        url = f"{BASE_URL}{path}"
        for attempt in range(1, MAX_RETRIES + 1):
            self._throttle()
            try:
                resp = self.session.get(url, params=params, timeout=TIMEOUT_SECONDS)
            except (requests.ConnectionError, requests.Timeout) as exc:
                if attempt == MAX_RETRIES:
                    raise GemiError(f"Σφάλμα δικτύου για {path}: {exc}") from exc
                backoff = 2 ** attempt
                print(f"  ! Σφάλμα δικτύου ({exc.__class__.__name__}), νέα προσπάθεια σε {backoff}s...")
                time.sleep(backoff)
                continue

            status = resp.status_code
            if status == 200:
                try:
                    return resp.json()
                except ValueError as exc:
                    raise GemiError(f"Μη έγκυρο JSON από {path}") from exc
            if status in (401, 403):
                raise GemiAuthError(
                    f"HTTP {status}: απορρίφθηκε το api_key ({self._error_text(resp)}). "
                    f"Έλεγξε ότι το header '{API_KEY_HEADER}' έχει έγκυρο κλειδί."
                )
            if status == 404:
                raise GemiNotFound(f"HTTP 404 για {path}")
            if status == 400:
                raise GemiError(f"HTTP 400 (λάθος παράμετροι): {self._error_text(resp)}")
            if status in (429, 503):
                if attempt == MAX_RETRIES:
                    raise GemiError(f"HTTP {status} για {path} μετά από {MAX_RETRIES} προσπάθειες "
                                    f"(rate limit ή μη διαθέσιμο σύστημα).")
                retry_after = resp.headers.get("Retry-After", "")
                wait = int(retry_after) if retry_after.isdigit() else 15 * attempt
                label = "Rate limit" if status == 429 else "Σύστημα μη διαθέσιμο"
                print(f"  ! HTTP {status} ({label}), αναμονή {wait}s (προσπάθεια {attempt}/{MAX_RETRIES})...")
                time.sleep(wait)
                continue
            raise GemiError(f"HTTP {status} για {path}: {self._error_text(resp)}")
        raise GemiError(f"Αποτυχία αιτήματος για {path}")  # δεν θα έπρεπε να φτάσει εδώ


# --------------------------------------------------------------------------
# Βοηθητικά
# --------------------------------------------------------------------------
# Λατινικοί χαρακτήρες που μοιάζουν με ελληνικούς (π.χ. "IKE" γραμμένο με λατινικά)
_LATIN_TO_GREEK = str.maketrans("ABEHIKMNOPTXYZ", "ΑΒΕΗΙΚΜΝΟΡΤΧΥΖ")


def norm(text):
    """Κανονικοποίηση για σύγκριση: χωρίς τόνους, κεφαλαία, ομοιόμορφοι χαρακτήρες."""
    text = unicodedata.normalize("NFD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    return " ".join(text.upper().translate(_LATIN_TO_GREEK).split())


def find_legal_type_id(client, target=TARGET_LEGAL_TYPE):
    legal_types = client.get("/metadata/legalTypes")
    if not isinstance(legal_types, list) or not legal_types:
        raise GemiError("Κενή/μη αναμενόμενη απάντηση από /metadata/legalTypes")

    wanted = norm(target)
    # 1) ακριβές ταίριασμα
    for lt in legal_types:
        if norm(lt.get("descr")) == wanted:
            return lt["id"], lt["descr"]
    # 2) ταίριασμα στο κύριο μέρος της περιγραφής
    core = norm("Ιδιωτική Κεφαλαιουχική Εταιρεία")
    candidates = [lt for lt in legal_types if core in norm(lt.get("descr"))]
    if len(candidates) == 1:
        return candidates[0]["id"], candidates[0]["descr"]

    options = candidates or [lt for lt in legal_types if "ΙΚΕ" in norm(lt.get("descr"))]
    listing = "\n".join(f"    id={lt.get('id')}: {lt.get('descr')}" for lt in options) or "    (κανένα)"
    raise GemiError(f"Δεν βρέθηκε μοναδική νομική μορφή για '{target}'. Υποψήφιες:\n{listing}")


def pick_primary_activity(activities):
    """
    Επιστρέφει (kad_id, kad_descr) της κύριας δραστηριότητας.
    Το Swagger ορίζει το πεδίο 'type' ως ελεύθερο κείμενο (χωρίς enum), οπότε
    ψάχνουμε για "ΚΥΡΙΑ" και αλλιώς πέφτουμε στην πρώτη ενεργή (χωρίς dtTo).
    """
    if not activities:
        return "", ""
    chosen = next((a for a in activities if "ΚΥΡΙ" in norm(a.get("type"))), None)
    if chosen is None:
        chosen = next((a for a in activities if not a.get("dtTo")), activities[0])
    act = chosen.get("activity") or {}
    return act.get("id") or "", act.get("descr") or ""


def build_row(company):
    """Μετατροπή αντικειμένου Company του API σε επίπεδη γραμμή. Τα ελλιπή πεδία γίνονται ''."""
    legal = company.get("legalType") or {}
    status = company.get("status") or {}
    muni = company.get("municipality") or {}

    street = " ".join(p for p in (company.get("street"), company.get("streetNumber")) if p)
    address = ", ".join(p for p in (street, company.get("zipCode")) if p)
    city_muni = " / ".join(dict.fromkeys(p for p in (company.get("city"), muni.get("descr")) if p))

    kad_id, kad_descr = pick_primary_activity(company.get("activities") or [])
    kad = f"{kad_id} - {kad_descr}" if kad_id and kad_descr else (kad_id or kad_descr)

    return {
        "gemi_number": company.get("arGemi", ""),
        "afm": company.get("afm") or "",
        "name": company.get("coNameEl") or "",
        "legal_type": legal.get("descr") or "",
        "status": status.get("descr") or "",
        "email": company.get("email") or "",
        "website": company.get("url") or "",
        "address": address,
        "city_municipality": city_muni,
        "primary_kad": kad,
    }


def print_table(rows, max_width=32):
    def cell(v):
        s = str(v) if v not in (None, "") else "-"
        return s if len(s) <= max_width else s[: max_width - 1] + "…"

    table = [[cell(r[c]) for c in CSV_COLUMNS] for r in rows]
    widths = [max(len(c), *(len(row[i]) for row in table)) for i, c in enumerate(CSV_COLUMNS)]
    line = "-+-".join("-" * w for w in widths)
    print(" | ".join(c.ljust(w) for c, w in zip(CSV_COLUMNS, widths)))
    print(line)
    for row in table:
        print(" | ".join(v.ljust(w) for v, w in zip(row, widths)))


def save_csv(rows, path=OUTPUT_CSV):
    # utf-8-sig ώστε το Excel να εμφανίζει σωστά τα ελληνικά
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------
def main():
    # Ασφαλής εκτύπωση ελληνικών σε Windows consoles
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    client = GemiClient()
    try:
        print(f"[1/3] Αναζήτηση νομικής μορφής: {TARGET_LEGAL_TYPE}")
        legal_id, legal_descr = find_legal_type_id(client)
        print(f"      -> id={legal_id} ({legal_descr})")

        print(f"[2/3] Αναζήτηση ενεργών εταιρειών (legalTypes={legal_id}, isActive=true, "
              f"resultsSize={LIMIT})")
        result = client.get("/companies", params={
            "legalTypes": legal_id,
            "isActive": "true",
            "resultsSize": LIMIT,
            "resultsOffset": 0,
            "resultsSortBy": "+arGemi",
        })
        found = (result or {}).get("searchResults") or []
        total = ((result or {}).get("searchMetadata") or {}).get("totalCount")
        if not found:
            print("Δεν βρέθηκαν εταιρείες.")
            return 1
        found = found[:LIMIT]  # ασφάλεια: ποτέ πάνω από LIMIT
        print(f"      -> συνολικά στο API: {total}, επεξεργασία των πρώτων {len(found)}")

        print(f"[3/3] Λήψη λεπτομερειών ({len(found)} requests)")
        rows = []
        for i, item in enumerate(found, 1):
            ar_gemi = item.get("arGemi")
            try:
                company = client.get(f"/companies/{ar_gemi}")
            except GemiNotFound:
                print(f"  ! {ar_gemi}: δεν βρέθηκε (404), χρήση στοιχείων αναζήτησης")
                company = item
            except GemiAuthError:
                raise
            except GemiError as exc:
                print(f"  ! {ar_gemi}: {exc} - χρήση στοιχείων αναζήτησης")
                company = item
            rows.append(build_row(company))
            print(f"      {i}/{len(found)} ΓΕΜΗ {ar_gemi} OK")

    except GemiAuthError as exc:
        print(f"\nΣΦΑΛΜΑ ΑΥΘΕΝΤΙΚΟΠΟΙΗΣΗΣ: {exc}")
        return 2
    except GemiError as exc:
        print(f"\nΣΦΑΛΜΑ API: {exc}")
        return 3
    except KeyboardInterrupt:
        print("\nΔιακοπή από τον χρήστη.")
        return 130

    print()
    print_table(rows)
    save_csv(rows)
    print(f"\nΑποθηκεύτηκαν {len(rows)} εγγραφές στο {OUTPUT_CSV}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
