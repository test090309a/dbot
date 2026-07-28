# DBot_admin – Discord-Bot mit lokaler Ollama-KI

Ein Discord-Bot, der auf deinem eigenen Server läuft und Anfragen von
Mitgliedern an ein **lokales Ollama-Modell** weiterleitet. Keine Cloud,
keine API-Kosten, volle Datenkontrolle.

---

## Funktionen

- **Slash-Commands:**
  - `/ask <Frage>` – stellt eine Frage an das aktive KI-Modell
  - `/model [Name]` – zeigt das aktuelle Modell an oder wechselt es
  - `/help` – Übersicht aller Befehle
  - `/clear` – löscht den flüchtigen Gesprächsverlauf des Kanals
- **Direkt-Antwort:** Der Bot antwortet, wenn du ihn mit `@DBot_admin` erwähnst.
- **Kontext:** Die letzten `CONTEXT_LENGTH` (Default: 10) Nachrichten pro Kanal
  fließen als Kontext in die Antwort ein.
- **Quellenhinweis:** Jede Antwort enthält das verwendete Modell.
- **Datenschutz:** Keine dauerhafte Speicherung. Verläufe leben nur im RAM.
- **Sicherheit:**
  - Token ausschließlich aus `.env`
  - Einfache Toxin-Erkennung (kann erweitert werden)
  - Verweigerung illegaler / beleidigender Anfragen
- **Discord-Limit-sicher:** Lange Antworten werden an Zeilenumbrüchen
  getrennt und auf mehrere Nachrichten aufgeteilt.

---

## Voraussetzungen

1. **Python 3.10+**
2. **Ollama** lokal installiert und laufend
   (<https://ollama.com/download>)
3. Ein **Discord-Bot-Account** mit den Intents
   - Message Content Intent
   - Server Members Intent (optional)
4. Der Bot wurde mit `bot` und `applications.commands`-Scopes auf deinen
   Server eingeladen.

### Empfohlene Modelle

| Modell                 | Gut für                                  |
| ---------------------- | ---------------------------------------- |
| `qwen2.5-coder:14b`    | Code, präzise technische Antworten       |
| `qwen3:14b`            | Aktuelles, leistungsfähiges Allround     |
| `phi4:latest`          | Logik, Reasoning                         |
| `llama2:13b`           | Solides Allround                         |
| `glm-4.7-flash:latest` | Schnell, modern                          |

Modell laden (Beispiel):

```bash
ollama pull qwen2.5-coder:14b
ollama serve   # falls nicht als Dienst läuft
```

---

## Installation

```bash
git clone <dein-repo>  # oder entpacken
cd discord_bot

python -m venv .venv
source .venv/bin/activate    # Windows: .venv\Scripts\activate

pip install -r requirements.txt

cp .env.example .env
# .env öffnen und DISCORD_TOKEN=<dein token> eintragen
```

---

## Konfiguration (`.env`)

| Variable            | Default                  | Bedeutung                              |
| ------------------- | ------------------------ | -------------------------------------- |
| `DISCORD_TOKEN`     | –                        | Bot-Token aus dem Discord-Portal       |
| `OLLAMA_HOST`       | `http://localhost:11434` | Ollama-Endpoint                        |
| `DEFAULT_MODEL`     | `qwen2.5-coder:14b`      | Initial aktives Modell                 |
| `CONTEXT_LENGTH`    | `10`                     | Anzahl Kontextnachrichten pro Kanal    |
| `ALLOWED_CHANNEL_IDS` | (leer)                 | Leere Liste = alle Kanäle              |
| `RESPONSE_TIMEOUT`  | `120`                    | Timeout (Sekunden) für Ollama          |

> Tipp: Wenn `ALLOWED_CHANNEL_IDS` gesetzt ist, reagiert der Bot **nur**
> in diesen Kanälen. Die IDs findest du in Discord via
> Rechtsklick auf den Kanal → `Kanal-ID kopieren` (Entwicklermodus an).

---

## Start

```bash
python bot.py
```

Beim Start erscheint in einem erreichbaren Kanal:

> **DBot_admin ist online.** Verwende `/help` für eine Befehlsübersicht.

---

## Discord-Portal – Checkliste

- [x] **Application**: DBot_admin
- [x] **Bot**-Bereich: Token generiert und in `.env` gespeichert
- [x] **Privileged Intents** aktiviert:
  - [x] Message Content Intent
  - [x] Server Members Intent (optional)
- [x] **OAuth2 → URL Generator**:
  - Scopes: `bot`, `applications.commands`
  - Permissions: `2147559424` (oder manuell auswählen)
- [x] Einladung-Link im Browser geöffnet → Bot deinem Server hinzugefügt

---

## Befehle im Detail

### `/ask <Frage>`

Stellt eine Frage an das aktive Modell. Beispiel:

```
/ask frage:Erkläre mir in 3 Sätzen, was Retrieval-Augmented Generation ist.
```

Antwort (Beispiel):

> Retrieval-Augmented Generation (RAG) kombiniert ein Sprachmodell mit
> einer externen Wissensquelle …
>
> _(Antwort mit `qwen2.5-coder:14b`)_

### `/model [Name]`

Ohne `Name`: zeigt aktuelles Modell + Liste aller lokal verfügbaren.
Mit `Name`: wechselt das Modell **serverweit**.

### `/clear`

Leert den flüchtigen Gesprächsverlauf dieses Kanals.

---

## Sicherheit & Datenschutz

- **Token:** Liegt ausschließlich in `.env`. Wird via `python-dotenv` geladen.
- **Verlauf:** Nur im RAM (`collections.deque`). Wird beim Beenden gelöscht.
- **Moderation:** Eine einfache Heuristik blockt grob beleidigende Inhalte.
  Für produktive Server empfiehlt sich ein zusätzlicher Moderations-Bot.
- **Illegale Inhalte:** Werden gemäß System-Prompt verweigert.

---

## Erweiterungsideen

- **Datenbank (SQLite/Postgres):** dauerhafte Gesprächsverläufe pro Kanal.
- **RAG:** Server-spezifische Dokumente via Embeddings in `chromadb` o. ä.
- **Voice:** Sprach-Channel-Integration mit `discord-ext-voice-recv`.
- **Rate-Limit:** Pro User / Kanal drosseln, um Missbrauch zu verhindern.
- **Reaktionen:** 👍/👎-Feedback sammeln und ins Prompt einbauen.

---

## Fehlerbehebung

| Problem                                | Lösung                                                       |
| -------------------------------------- | ------------------------------------------------------------ |
| `DISCORD_TOKEN fehlt`                  | `.env` anlegen und Token eintragen                           |
| `Ollama antwortete mit Status 404`     | Modellname falsch → `/model` ohne Argument zeigt Verfügbare  |
| Bot reagiert nicht auf Nachrichten     | Message Content Intent **muss** im Portal aktiviert sein     |
| Bot antwortet nur in bestimmten Kanälen| `ALLOWED_CHANNEL_IDS` prüfen oder leeren                     |
| Antworten dauern sehr lange            | Kleineres Modell wählen (`llama2:13b` oder `phi4`)           |

---

## Lizenz

MIT – frei verwendbar, bitte mit Hinweis auf den Autor.
