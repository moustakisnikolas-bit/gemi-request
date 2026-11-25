# ΓΕΜΗ OpenData API – PoC

Μικρό proof-of-concept που ψάχνει τις **πρώτες 10 ενεργές ΙΚΕ** στο ΓΕΜΗ OpenData API
και τις εκτυπώνει σε πίνακα + αποθηκεύει σε `test_ike_companies.csv`.

## Εκτέλεση

```bash
pip install -r requirements.txt
python gemi_test.py
```

Χρειάζεται Python 3.8+ και πρόσβαση στο `opendata-api.businessportal.gr`.

## Τι επαληθεύτηκε από την επίσημη τεκμηρίωση

Πηγές: Swagger spec (`https://opendata-api.businessportal.gr/api-docs`) και
techdocs (`https://opendata.businessportal.gr/techdocs/`).

| Θέμα | Τιμή |
|---|---|
| Base URL | `https://opendata-api.businessportal.gr/api/opendata/v1` |
| Authentication | HTTP **header** με όνομα `api_key` (όχι query param) |
| Δοκιμαστικό κλειδί | `api-docs-key` (με παύλες – έτσι αναγράφεται στο techdocs) |
| Νομικές μορφές | `GET /metadata/legalTypes` |
| Αναζήτηση | `GET /companies?legalTypes=<id>&isActive=true&resultsSize=10` |
| Λεπτομέρειες | `GET /companies/{arGemi}` |

Σημειώσεις από το Swagger:

- Στο `/companies` πρέπει να δοθεί τουλάχιστον ένα κριτήριο. Τα κριτήρια συνδυάζονται με AND.
- Το `resultsSize` έχει μέγιστο 200 (εδώ 10).
- Για το αν μια εταιρεία είναι ενεργή συνιστάται το `isActive` (υπάρχουν πολλές μη ενεργές καταστάσεις), γι' αυτό χρησιμοποιείται αυτό και όχι συγκεκριμένο status id.
- Το test key έχει περιορισμένο αριθμό κλήσεων ανά IP και δεν υποκαθιστά προσωπικό κλειδί.

## Πεδία εξόδου

| Στήλη | Πεδίο API |
|---|---|
| `gemi_number` | `arGemi` |
| `afm` | `afm` |
| `name` | `coNameEl` |
| `legal_type` | `legalType.descr` |
| `status` | `status.descr` |
| `email` | `email` |
| `website` | `url` |
| `address` | `street` + `streetNumber`, `zipCode` |
| `city_municipality` | `city` / `municipality.descr` |
| `primary_kad` | `activities[]` – η δραστηριότητα με type που περιέχει «Κύρια», αλλιώς η πρώτη ενεργή |

Τα ελλιπή πεδία εμφανίζονται ως `-` στον πίνακα και κενά στο CSV.

## Χειρισμός σφαλμάτων

- **401/403**: μήνυμα για άκυρο `api_key`, έξοδος με κωδικό 2.
- **429/503**: αναμονή (σέβεται το `Retry-After` αν υπάρχει, αλλιώς 15s × προσπάθεια) και έως 4 προσπάθειες.
- **400/5xx**: εμφανίζεται το `ErrorEntry` (`code: message`) του API.
- **404 σε λεπτομέρειες**: χρησιμοποιούνται τα στοιχεία της αναζήτησης.
- **Σφάλματα δικτύου/timeout**: exponential backoff.
- Παύση 1s ανάμεσα στα requests (`DELAY_SECONDS` στο script).

Σύνολο κλήσεων ανά εκτέλεση: 1 (legalTypes) + 1 (αναζήτηση) + 10 (λεπτομέρειες) = **12**.

## Σημειώσεις

- Το CSV είναι UTF-8 με BOM ώστε το Excel να δείχνει σωστά τα ελληνικά. Το Excel μπορεί να αφαιρέσει τα αρχικά μηδενικά του ΑΦΜ· για να τα κρατήσεις, κάνε import της στήλης ως κείμενο.
- Κλειδί: στον κώδικα υπάρχει μόνο το δημόσιο test key. Αν αργότερα αποκτήσεις προσωπικό κλειδί, δώσε το μέσω της μεταβλητής περιβάλλοντος `GEMI_API_KEY` και μην το γράψεις στον κώδικα.
- Τα δεδομένα ΓΕΜΗ διατίθενται με άδεια ODC-BY-1.0 (απαιτείται αναφορά πηγής).
