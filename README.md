# Crawler/Tracker con notifiche Telegram

Monitora offerte su Google Shopping (architettura a plugin, estendibile ad altri
marketplace) e invia notifiche Telegram in tempo reale per nuove offerte e cali di
prezzo significativi, senza mai duplicare notifiche per lo stesso prezzo.

## Setup

1. **Python 3.11+** richiesto.
2. Crea un virtualenv e installa le dipendenze:
   ```bash
   python -m venv .venv
   .venv\Scripts\activate   # Windows
   pip install -r requirements-dev.txt
   playwright install chromium
   ```
3. Copia `.env.example` in `.env` e compila i valori:
   ```bash
   copy .env.example .env
   ```
   - `TELEGRAM_BOT_TOKEN`: crea un bot con [@BotFather](https://t.me/BotFather) su Telegram, copia il token che ti fornisce.
   - `TELEGRAM_CHAT_ID`: scrivi un messaggio al tuo bot, poi apri
     `https://api.telegram.org/bot<TOKEN>/getUpdates` nel browser e leggi il campo
     `chat.id` nella risposta JSON (in alternativa usa il bot [@userinfobot](https://t.me/userinfobot)).
4. Modifica `config/targets.json` con le ricerche che vuoi monitorare (query, prezzo
   massimo, parole chiave da includere/escludere, venditore, condizione).
5. Rivedi `config/config.yaml` per intervalli di polling, proxy opzionali e soglia di
   ri-notifica sui cali di prezzo (`default_renotify_drop_pct`, default 5%).

## Esecuzione

- Singolo ciclo di prova, senza inviare notifiche reali:
  ```bash
  python main.py --once --dry-run
  ```
- Singolo ciclo, invio reale su Telegram:
  ```bash
  python main.py --once
  ```
- Loop continuo in background (comportamento di default):
  ```bash
  python main.py
  ```

**Flag opzionali:** usa `--config` e `--targets` per specificare percorsi alternativi ai file di configurazione (default: `config/config.yaml` e `config/targets.json`):
```bash
python main.py --once --dry-run --config custom/config.yaml --targets custom/targets.json
```

## Test

```bash
pytest -v
```

Tutti i test girano senza rete o browser reale, usando un adapter mock
(`scrapers/plugins/mock_adapter.py`) e fixture HTML statiche per il parsing di Google
Shopping. Un test è marcato `skip` finché non viene catturata una fixture HTML reale
(vedi sotto).

## Calibrare l'adapter Google Shopping su una pagina reale

I selettori CSS in `scrapers/plugins/google_shopping.py` sono un punto di partenza:
Google cambia la struttura della pagina periodicamente. Per verificarli/aggiornarli:

1. `playwright install chromium` (se non già fatto).
2. Apri manualmente `https://www.google.com/search?tbm=shop&q=<query di prova>` con
   Playwright o un browser normale, salva l'HTML della pagina in
   `tests/fixtures/google_shopping_sample.html`.
3. Ispeziona l'HTML salvato e confronta con i selettori in `parse_listings()`.
4. Aggiorna i selettori se necessario, poi esegui `pytest tests/test_google_shopping.py -v`:
   il test `test_parse_listings_against_real_fixture` dovrebbe passare.

## Aggiungere un nuovo adapter/marketplace

1. Crea `scrapers/plugins/<nome>.py` con una classe che estende
   `scrapers.base.BaseScraper` e implementa `async def search(self, target) -> list[ListingResult]`.
2. Registra la classe in `SCRAPER_REGISTRY` in `core/engine.py`.
3. Usa `"adapter": "<nome>"` nei target di `config/targets.json`.
4. Aggiungi test di parsing con fixture HTML statiche, seguendo lo schema di
   `tests/test_google_shopping.py`.

## Struttura del progetto

```
crawler/
├── config/                  # config.yaml, targets.json
├── core/                     # engine, database, notifier, config loader, antibot, filters
├── scrapers/
│   ├── base.py                # interfaccia BaseScraper / ListingResult
│   └── plugins/                # adapter per marketplace/motori di ricerca
├── tests/
└── main.py                   # entrypoint CLI
```
