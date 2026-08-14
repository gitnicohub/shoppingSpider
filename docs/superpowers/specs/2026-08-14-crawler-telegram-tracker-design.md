# Crawler/Tracker universale con notifiche Telegram — Design

Data: 2026-08-14

## Obiettivo

Applicazione CLI/background worker in Python che monitora periodicamente offerte/prodotti
su marketplace/motori di ricerca (architettura ad adapter/plugin) e notifica in tempo reale
via Telegram Bot quando un'offerta nuova o un calo di prezzo significativo viene rilevato,
senza mai duplicare notifiche per lo stesso stato di prezzo.

## Stack

- Python 3.11+
- Playwright (scraping con rendering JS) + httpx (dove basta HTTP semplice)
- SQLAlchemy + SQLite per persistenza locale
- python-telegram-bot (async) per l'invio messaggi
- pydantic per validazione config
- pytest per i test

## Scope MVP

- Un solo adapter reale: **Google Shopping** (rendering JS via Playwright, anti-bot aggressivo
  → richiede stealth, user-agent rotation, jitter, backoff, supporto proxy opzionale).
- Un adapter `mock_adapter.py` deterministico usato solo nei test, per validare l'engine e la
  pipeline di dedup/notifica senza dipendere dalla rete o da Google.
- Architettura a plugin (`scrapers/plugins/`) pensata per aggiungere altri adapter in futuro
  (marketplace C2C, API ufficiali, altri motori di ricerca) senza toccare il core.

## Architettura e struttura directory

```
crawler/
├── config/
│   ├── config.yaml          # Token bot, chat_id, intervalli min/max, proxy list, concurrency
│   └── targets.json         # Lista target: query, adapter, max_price, keywords, seller, condition, renotify_drop_pct
├── core/
│   ├── engine.py            # Loop asyncio: itera i target, chiama l'adapter giusto, passa risultati a dedup+notifier
│   ├── database.py          # SQLAlchemy + SQLite: modello Listing, funzioni process_listing/is_new/has_significant_drop
│   ├── notifier.py          # Formattazione messaggio + invio via python-telegram-bot (async)
│   ├── config_loader.py     # Carica/valida config.yaml e targets.json (pydantic)
│   └── antibot.py           # User-agent rotation, jitter/delay helper, proxy picker, retry su 429/403/timeout
├── scrapers/
│   ├── base.py               # ABC: BaseScraper con metodo async search(target) -> list[ListingResult]
│   └── plugins/
│       ├── google_shopping.py   # Adapter reale MVP, Playwright
│       └── mock_adapter.py      # Adapter fittizio deterministico, usato nei test
├── tests/
│   ├── test_database.py
│   ├── test_notifier.py
│   └── test_google_shopping.py
├── .env.example
├── README.md
└── main.py                   # CLI entrypoint: carica config, avvia engine.run_forever()
```

### Flusso dati per ciclo

1. `engine.py` carica `targets.json`; per ogni target seleziona l'adapter tramite un registry
   (`{"google_shopping": GoogleShoppingScraper}`).
2. Chiama `await scraper.search(target)` → lista di `ListingResult` (titolo, prezzo, url,
   venditore, condizione).
3. Ogni risultato passa a `database.process_listing()` che decide l'azione (vedi sotto).
4. Se dovuta una notifica, `notifier.py` formatta e invia il messaggio Telegram; solo dopo
   l'invio (o il tentativo con retry esaurito) `database.py` aggiorna `last_notified_price`.
5. Jitter randomizzato (`antibot.py`) tra un target e il successivo (`jitter_between_targets_seconds`);
   a fine ciclo, pausa più ampia (`min_interval_seconds`–`max_interval_seconds`) prima del ciclo successivo.
6. Esecuzione **sequenziale, non concorrente** (`concurrency: 1`): un solo target alla volta,
   per minimizzare il pattern "burst" che innesca i blocchi anti-bot di Google. Il parametro
   `concurrency` è riservato per un'eventuale evoluzione futura a concorrenza limitata.

## Modello dati

```python
class Listing(Base):
    id: int (PK)
    target_id: str          # da targets.json
    adapter: str             # "google_shopping"
    external_id: str         # hash stabile (dominio+titolo+venditore, o id nativo se disponibile)
    title: str
    url: str
    seller: str | None
    condition: str | None
    first_seen_at: datetime
    last_seen_at: datetime
    first_price: float
    last_price: float
    last_notified_price: float | None
    notified_count: int

    __table_args__ = (UniqueConstraint("target_id", "adapter", "external_id"),)
```

`external_id` invece del solo URL: gli URL di Google Shopping spesso portano parametri di
tracking volatili tra un fetch e l'altro. `external_id` è un hash normalizzato che resta
stabile anche se l'URL cambia leggermente; l'URL completo viene comunque salvato/aggiornato
per il link nel messaggio Telegram.

### Logica di deduplicazione (`database.process_listing`)

```
esistente = query Listing per (target_id, adapter, external_id)

se non esistente:
    crea nuovo Listing (first_price = last_price = prezzo corrente)
    → AZIONE: notifica "nuova offerta"

altrimenti:
    aggiorna last_seen_at, last_price = prezzo corrente
    drop_pct = (last_notified_price - prezzo_corrente) / last_notified_price

    se drop_pct >= target.renotify_drop_pct (default globale configurabile, es. 0.05):
        → AZIONE: notifica "prezzo sceso ulteriormente"
        aggiorna last_notified_price = prezzo corrente
        notified_count += 1
    altrimenti:
        → nessuna azione, solo update silenzioso dei campi last_*
```

Il confronto è sempre contro **l'ultimo prezzo notificato**, non contro il minimo storico
assoluto: garantisce che lo stesso prezzo non generi mai due notifiche, e che piccoli
rimbalzi su/giù non producano spam. Una nuova notifica scatta solo quando il prezzo scende
di almeno `renotify_drop_pct` rispetto all'ultima notifica inviata.

## Configurazione

`config/config.yaml`:

```yaml
telegram:
  bot_token: "${TELEGRAM_BOT_TOKEN}"   # da .env, mai committato
  chat_id: "${TELEGRAM_CHAT_ID}"

polling:
  min_interval_seconds: 1800   # 30 min
  max_interval_seconds: 3600   # 60 min
  jitter_between_targets_seconds: [5, 20]

antibot:
  user_agents: [...]            # pool per rotazione
  proxies: []                    # opzionale, lista "http://user:pass@host:port"; vuota = IP diretto
  max_retries: 3
  backoff_base_seconds: 5

concurrency: 1                   # riservato per evoluzione futura, MVP resta 1
```

`config/targets.json`: array di target con `id`, `adapter`, `query`, `max_price`,
`keywords_include`/`keywords_exclude`, `seller` (opzionale), `condition` (opzionale),
`renotify_drop_pct` (override opzionale del default globale).

`core/config_loader.py` valida schema e tipi con pydantic a startup: se manca `bot_token` o
un target ha campi invalidi, l'app fallisce subito con errore chiaro invece di crashare a
metà ciclo.

## Notifiche Telegram

`core/notifier.py` usa `python-telegram-bot` (async). Funzione `format_message(listing,
event_type)` con `event_type` in `{"new", "price_drop"}`, Markdown coerente con:

```
🔥 *NUOVA OFFERTA RILEVATA!*
📦 *Prodotto:* Nome Prodotto
💰 *Prezzo:* 49.99 € (Prezzo precedente/target: 75.00 €)
🏪 *Piattaforma:* NomeStore
🔗 [Vai all'offerta](https://...)
```

L'invio ha retry leggero (2 tentativi) su errore di rete Telegram; se fallisce comunque,
logga e continua — il listing resta salvato/aggiornato in DB indipendentemente dall'esito
dell'invio, quindi nessun dato viene perso e non si blocca il ciclo.

## Gestione errori e resilienza

- Ogni chiamata `scraper.search(target)` è wrappata in try/except dedicato in `engine.py`.
- Su `403`/`429`: backoff esponenziale con jitter (`antibot.py`), fino a `max_retries`; se
  esauriti, skip del target per questo ciclo, log WARNING con target id ed errore, il loop
  continua con il target successivo.
- Su `TimeoutError` (Playwright): stesso trattamento, retry poi skip.
- Su eccezioni impreviste (es. parsing HTML cambiato): log ERROR con traceback, skip del
  target, **mai crash del processo intero** — un adapter rotto non deve fermare gli altri
  target né l'intero monitoraggio.
- Playwright gira con context stealth (es. `playwright-stealth`) e user-agent random per
  tentativo; proxy opzionale da `config.antibot.proxies`.

## Testing

- `tests/test_database.py`: (a) listing nuovo → notifica; (b) stesso prezzo → mai una
  seconda notifica; (c) calo sotto soglia → nessuna notifica; (d) calo sopra soglia →
  notifica e aggiornamento di `last_notified_price`.
- `tests/test_notifier.py`: mock della chiamata HTTP a Telegram, verifica formattazione
  messaggio e che il retry scatti su errore simulato.
- `tests/test_google_shopping.py`: nessuna chiamata di rete reale; fixture HTML salvata su
  disco (anonimizzata), test solo sul parsing → lista di `ListingResult`.
- `scrapers/plugins/mock_adapter.py` per test end-to-end dell'engine (dedup + notifica)
  senza toccare Playwright né la rete.
- README con istruzioni: creare `.env` da `.env.example`, ottenere bot token da BotFather,
  ottenere `chat_id` (via `getUpdates` o bot `@userinfobot`), comando per un singolo ciclo
  di prova senza invio reale (`python main.py --once --dry-run`).

## Fuori scope (per ora)

- Concorrenza tra target (riservata come parametro futuro, non implementata nell'MVP).
- Altri adapter oltre a Google Shopping (l'architettura li supporta, ma non vengono
  implementati in questa iterazione).
- Dashboard/UI web: solo CLI + notifiche Telegram.
