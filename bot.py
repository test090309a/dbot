"""
DBot_admin – Discord-Bot mit lokaler Ollama-KI-Anbindung
=========================================================

Ein intelligenter Discord-Bot, der Mitglieder in erlaubten Kanälen unterstützt.
Die KI-Antworten werden von einem lokalen Ollama-Modell (http://localhost:11434)
Vorsicht OLLAMA lokale Variable ist möglicherweise gesetzt.
erzeugt. Slash-Commands: /ask, /model, /help, /clear.
Mit @DBot_admin werden direkt Antworten erzeugt.

Sicherheitshinweise:
  * Bot-Token IMMER aus der Umgebungsvariable / .env-Datei laden.
  * Niemals Tokens in den Quellcode schreiben.
  * Datenschutz: Es werden keine personenbezogenen Daten dauerhaft gespeichert.
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
import re
from collections import defaultdict, deque
from typing import Deque, Dict, List, Optional

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

import colorlog

import os
# ===== TEST: .env wird geladen? =====
# print("ENV-Variable OLLAMA_HOST:", os.getenv("OLLAMA_HOST"))
# ====================================
# ---------------------------------------------------------------------------
# Konfiguration
# ---------------------------------------------------------------------------

# load_dotenv()
# Lade .env und überschreibe existierende Umgebungsvariablen
load_dotenv(override=True)

# ===== TEST: Wurde die .env geladen? =====
# print("DEBUG: load_dotenv() wurde ausgeführt.")
# print("DEBUG: OLLAMA_HOST aus os.getenv:", os.getenv("OLLAMA_HOST"))
# print("DEBUG: OLLAMA_HOST aus os.environ:", os.environ.get("OLLAMA_HOST"))
# =========================================

# DISCORD_TOKEN: Optional[str] = os.getenv("DISCORD_TOKEN")
# OLLAMA_HOST: str = os.getenv("OLLAMA_HOST", "http://localhost:11434")
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434")
DEFAULT_MODEL: str = os.getenv("DEFAULT_MODEL", "ornith-state:latest") #qwen2.5-coder:14b
CONTEXT_LENGTH: int = int(os.getenv("CONTEXT_LENGTH", "10"))  # letzte N Nachrichten
ALLOWED_CHANNEL_IDS: List[int] = [
    int(x) for x in os.getenv("ALLOWED_CHANNEL_IDS", "").split(",") if x.strip()
]
RESPONSE_TIMEOUT: float = float(os.getenv("RESPONSE_TIMEOUT", "120"))

# Discord-Limit
DISCORD_MAX_CHARS: int = 2000

# Logging
import logging
import colorlog

# ===== FARBIGES LOGGING =====
def setup_logging():
    """Richtet farbiges, übersichtliches Logging ein."""
    logger = logging.getLogger("DBot_admin")
    logger.setLevel(logging.DEBUG)  # DEBUG, INFO, WARNING, ERROR, CRITICAL

    # Falls schon Handler existieren, entfernen (verhindert doppelte Ausgaben)
    if logger.handlers:
        logger.handlers.clear()

    # Format: Zeit [Level] Modul: Nachricht (Datei:Zeile)
    log_format = (
        "%(log_color)s%(asctime)s [%(levelname)-8s] %(name)s%(reset)s: "
        "%(message)s"
    )
    date_format = "%H:%M:%S"

    # Console-Handler mit Farben
    console_handler = colorlog.StreamHandler()
    console_handler.setLevel(logging.DEBUG)

    # Farben definieren
    log_colors = {
        'DEBUG': 'cyan',
        'INFO': 'green',
        'WARNING': 'yellow',
        'ERROR': 'red',
        'CRITICAL': 'red,bg_white',
    }

    formatter = colorlog.ColoredFormatter(
        log_format,
        datefmt=date_format,
        log_colors=log_colors,
        reset=True,
    )
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # Discord-spezifische Logs (wie discord.client) auf WARNING setzen, um Rauschen zu reduzieren
    logging.getLogger("discord").setLevel(logging.WARNING)
    logging.getLogger("discord.client").setLevel(logging.WARNING)
    logging.getLogger("discord.gateway").setLevel(logging.WARNING)

    return logger


log = setup_logging()

# ---------------------------------------------------------------------------
# Persona / System-Prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = (
    "Du bist ein erfahrener, ruhiger, einfühlsamer DevOps-Ingenieur und "
    "beantwortest technische Fragen präzise mit Code-Beispielen mit einem trockenen Humor. "
    "auf einem Discord-Server. Deine Persönlichkeit ist freundlich, sachlich "
    "und zuvorkommend, aber stets professionell. Du antwortest in derselben "
    "Sprache, in der du angesprochen wirst. Wenn du etwas nicht weißt, sagst "
    "du es ehrlich, anstatt zu halluzinieren. Du verweigerst Antworten auf "
    "illegale, beleidigende oder gefährliche Anfragen und weist in solchen "
    "Fällen höflich auf die Server-Regeln hin."
)

# ---------------------------------------------------------------------------
# Datenstruktur: Pro-Kanal-Verlauf (flüchtig, nur im RAM)
# ---------------------------------------------------------------------------

channel_histories: Dict[int, Deque[Dict[str, str]]] = defaultdict(
    lambda: deque(maxlen=CONTEXT_LENGTH)
)

# Pro-Guild-Modellauswahl
guild_models: Dict[int, str] = {}

# ---------------------------------------------------------------------------
# Ollama-Client
# ---------------------------------------------------------------------------


class OllamaClient:
    """Schlanker async-Client für die lokale Ollama-API."""

    def __init__(self, host: str) -> None:
        # Robustheit: fehlendes http://-Schema automatisch ergänzen.
        # So akzeptiert die Konfiguration z. B. "127.0.0.1:11434"
        # genauso wie "http://127.0.0.1:11434".
        normalized = host.strip().rstrip("/")
        if not normalized.lower().startswith(("http://", "https://")):
            normalized = f"http://{normalized}"
        self.host = normalized
        self._session: Optional[aiohttp.ClientSession] = None
        log.info("Ollama-Host: %s", self.host)

    async def health_check(self) -> bool:
        """Prüft, ob der Ollama-Server erreichbar ist."""
        try:
            session = await self._ensure_session()
            async with session.get(
                f"{self.host}/api/tags",
                timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                return resp.status == 200
        except Exception as exc:
            log.warning("Ollama-Health-Check fehlgeschlagen: %s", exc)
            return False

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    async def list_models(self) -> List[str]:
        """Gibt alle lokal verfügbaren Modelle zurück."""
        session = await self._ensure_session()
        url = f"{self.host}/api/tags"
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            resp.raise_for_status()
            data = await resp.json()
        return [m["name"] for m in data.get("models", [])]

    async def generate(
        self,
        model: str,
        prompt: str,
        history: Optional[List[Dict[str, str]]] = None,
        system: str = SYSTEM_PROMPT,
    ) -> str:
        """Sendet einen Prompt an Ollama und gibt die Antwort zurück."""
        session = await self._ensure_session()
        url = f"{self.host}/api/generate"

        # Kontext zusammensetzen: System + Verlauf + aktuelle Frage
        full_prompt = ""
        if system:
            full_prompt += f"System: {system}\n\n"
        if history:
            for entry in history:
                role = "User" if entry["role"] == "user" else "Assistant"
                full_prompt += f"{role}: {entry['content']}\n"
        full_prompt += f"User: {prompt}\nAssistant:"

        payload = {
            "model": model,
            "prompt": full_prompt,
            "stream": False,
        }

        timeout = aiohttp.ClientTimeout(total=RESPONSE_TIMEOUT)
        async with session.post(url, json=payload, timeout=timeout) as resp:
            if resp.status != 200:
                body = await resp.text()
                raise OllamaError(
                    f"Ollama antwortete mit Status {resp.status}: {body[:200]}"
                )
            data = await resp.json()
        return (data.get("response") or "").strip()


class OllamaError(RuntimeError):
    """Wird geworfen, wenn die Ollama-API einen Fehler zurückgibt."""


ollama = OllamaClient(OLLAMA_HOST)

# ---------------------------------------------------------------------------
# Discord-Bot Setup
# ---------------------------------------------------------------------------

intents = discord.Intents.default()
intents.message_content = True  # Message Content Intent
intents.members = True          # Server Members Intent (optional)
intents.guilds = True
intents.messages = True

bot = commands.Bot(command_prefix="!", intents=intents)


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------


def is_allowed_channel(channel: discord.abc.Snowflake) -> bool:
    """Wenn ALLOWED_CHANNEL_IDS leer ist, sind alle Kanäle erlaubt."""
    if not ALLOWED_CHANNEL_IDS:
        return True
    return channel.id in ALLOWED_CHANNEL_IDS


def split_message(text: str, max_length: int = DISCORD_MAX_CHARS) -> List[str]:
    """Zerteilt eine Nachricht an Zeilenumbrüchen, damit das Discord-Limit
    (2000 Zeichen) nicht überschritten wird."""
    if len(text) <= max_length:
        return [text]

    chunks: List[str] = []
    remaining = text
    while len(remaining) > max_length:
        # Versuche, am nächsten Zeilenumbruch zu trennen
        cut = remaining.rfind("\n", 0, max_length)
        if cut == -1:
            cut = remaining.rfind(" ", 0, max_length)
        if cut == -1:
            cut = max_length
        chunks.append(remaining[:cut].rstrip())
        remaining = remaining[cut:].lstrip()
    if remaining:
        chunks.append(remaining)
    return chunks


def add_to_history(channel_id: Optional[int], role: str, content: str) -> None:
    """Schreibt eine Nachricht in den flüchtigen Kanal-Verlauf."""
    key = 0 if channel_id is None else channel_id
    channel_histories[key].append({"role": role, "content": content})


def get_history(channel_id: Optional[int]) -> List[Dict[str, str]]:
    """Gibt eine Kopie des aktuellen Kanal-Verlaufs zurück."""
    key = 0 if channel_id is None else channel_id
    return list(channel_histories[key])


async def _answer_with_ai(
    channel, prompt: str, *, author_name: str = "", guild_id: Optional[int] = None
) -> None:
    """Interne Helferfunktion: Fragt Ollama an und sendet die Antwort in den Kanal.
    Fehler werden im Kanal gemeldet; Verlauf wird aktualisiert.
    """
    if looks_toxic(prompt):
        await channel.send(
            "Diese Anfrage verletzt die Server-Regeln. Ich kann darauf nicht antworten."
        )
        return

    model = (
        guild_models[guild_id]
        if guild_id is not None and guild_id in guild_models
        else DEFAULT_MODEL
    )

    history = get_history(channel.id if hasattr(channel, "id") else 0)
    try:
        answer = await ollama.generate(model=model, prompt=prompt, history=history)
    except OllamaError as exc:
        log.error("Ollama-Fehler: %s", exc)
        await channel.send(
            f"Fehler bei der KI-Anfrage: `{exc}`\n"
            f"Bitte prüfe, ob Ollama läuft (`ollama serve`) und `OLLAMA_HOST` in `.env` korrekt gesetzt ist"
        )
        return
    except asyncio.TimeoutError:
        await channel.send(
            "Die Anfrage hat das Zeitlimit überschritten. Versuche es spaeter erneut oder wechsle das Modell mit `/model`."
        )
        return
    except aiohttp.ClientError as exc:
        log.error("HTTP-Client-Fehler: %s", exc)
        await channel.send(
            f"Konnte Ollama unter `{OLLAMA_HOST}` nicht erreichen: `{exc}`"
        )
        return

    add_to_history(channel.id if hasattr(channel, "id") else 0, "user", prompt)
    add_to_history(channel.id if hasattr(channel, "id") else 0, "assistant", answer)

    footer = f"\n\n— _(Antwort mit `{model}`)_"
    for chunk in split_message(answer + footer):
        await channel.send(chunk)



# Heuristik: einfache, konservativ-eingestellte Moderation gegen toxische Inhalte
TOXIC_PATTERNS = [
    r"\b(hassrede|nazi|vergewaltig|missbrauch)\b",
    r"\b(kill yourself|kys)\b",
]


def looks_toxic(text: str) -> bool:
    text_l = text.lower()
    return any(re.search(p, text_l) for p in TOXIC_PATTERNS)


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------


@bot.event
async def on_ready() -> None:
    # bot.user kann theoretisch None sein (statischer Checker); daher sicher auslesen
    bot_user_name = getattr(bot.user, "name", "(unbekannt)")
    bot_user_id = getattr(bot.user, "id", "(unbekannt)")
    log.info("Bot ist online als %s (ID: %s)", bot_user_name, bot_user_id)

    # Ollama-Health-Check: warnt früh, wenn der KI-Server nicht erreichbar ist.
    if await ollama.health_check():
        log.info("Ollama ist erreichbar unter %s", OLLAMA_HOST)
    else:
        log.warning(
            "Ollama ist unter %s NICHT erreichbar. "
            "Prüfe, ob `ollama serve` läuft und OLLAMA_HOST in .env korrekt ist.",
            OLLAMA_HOST,
        )

    try:
        synced = await bot.tree.sync()
        log.info("Slash-Commands synchronisiert: %d", len(synced))
    except Exception as exc:
        log.error("Fehler beim Synchronisieren der Slash-Commands: %s", exc)

    # Statusmeldung in alle erlaubten Kanäle senden (oder ersten verfügbaren)
    channels = []
    if ALLOWED_CHANNEL_IDS:
        for cid in ALLOWED_CHANNEL_IDS:
            ch = bot.get_channel(cid)
            if ch:
                channels.append(ch)
    else:
        for guild in bot.guilds:
            for ch in guild.text_channels:
                channels.append(ch)
                break  # einer reicht für die Statusmeldung
            break

    for ch in channels:
        try:
            await ch.send(
                "**DBot_admin ist online.** Verwende `/help` für eine "
                "Befehlsübersicht."
            )
        except discord.Forbidden:
            log.warning("Keine Berechtigung für Kanal %s", ch)


@bot.event
async def on_message(message: discord.Message) -> None:
    """Reagiert auf Nachrichten in erlaubten Kanälen, sofern der Bot
    erwähnt oder direkt angesprochen wird (um Spam zu vermeiden)."""
    # === DEBUG ===
    print(f"Nachricht von {message.author}: {message.content}")
    print(f"Bot erwähnt? {bot.user in message.mentions}")
    print(f"Erlaubter Kanal? {is_allowed_channel(message.channel)}")
    # =============
    # Eigene und andere Bot-Nachrichten ignorieren (Schutz vor Endlosschleifen)
    if message.author.bot:
        return

    if not is_allowed_channel(message.channel):
        return

    # Slash-Commands weiterhin durchlassen
    await bot.process_commands(message)

    if bot.user is None:
        return

    # Nur reagieren, wenn der Bot erwähnt wird
    if bot.user not in message.mentions:
        return

    # Inhalt ohne die Bot-Erwähnung
    content = re.sub(f"<@!?{bot.user.id}>", "", message.content).strip()
    if not content:
        await message.channel.send(
            "Hallo! Wie kann ich dir helfen? Nutze `/help` für eine Übersicht."
        )
        return

    await _answer_with_ai(
        message.channel,
        content,
        author_name=str(message.author.display_name),
        guild_id=message.guild.id if message.guild else None,
    )


# ---------------------------------------------------------------------------
# Slash-Commands
# ---------------------------------------------------------------------------


ask_group = app_commands.Group(
    name="dbot", description="DBot_admin – KI-gestützte Discord-Assistenz"
)


@ask_group.command(name="help", description="Zeigt eine Übersicht aller Befehle.")
async def help_cmd(interaction: discord.Interaction) -> None:
    embed = discord.Embed(
        title="DBot_admin – Befehlsübersicht",
        color=discord.Color.blurple(),
    )
    embed.add_field(
        name="`/ask <Frage>`",
        value="Stellt dem aktuell aktiven Ollama-Modell eine Frage.",
        inline=False,
    )
    embed.add_field(
        name="`/model [Name]`",
        value="Zeigt das aktuelle Modell oder wechselt es (z. B. "
        "`/model qwen3:14b`).",
        inline=False,
    )
    embed.add_field(
        name="`/clear`",
        value="Löscht den Gesprächsverlauf des aktuellen Kanals.",
        inline=False,
    )
    embed.add_field(
        name="Erwähnung",
        value="Du kannst mich auch direkt mit `@DBot_admin` in einem Kanal "
        "ansprechen.",
        inline=False,
    )
    embed.set_footer(text="Antworten werden lokal von Ollama erzeugt.")
    await interaction.response.send_message(embed=embed, ephemeral=True)


@ask_group.command(
    name="ask",
    description="Stelle dem aktiven Ollama-Modell eine Frage.",
)
@app_commands.describe(frage="Deine Frage an die KI")
async def ask_cmd(interaction: discord.Interaction, frage: str) -> None:
    await interaction.response.defer(thinking=True)
    if looks_toxic(frage):
        await interaction.followup.send(
            "Diese Anfrage verletzt die Server-Regeln. Ich kann darauf nicht "
            "antworten."
        )
        return

    guild_id = interaction.guild_id
    model = (
        guild_models[guild_id]
        if guild_id is not None and guild_id in guild_models
        else DEFAULT_MODEL
    )
    history = get_history(interaction.channel_id or 0)
    try:
        answer = await ollama.generate(model=model, prompt=frage, history=history)
    except OllamaError as exc:
        log.error("Ollama-Fehler: %s", exc)
        await interaction.followup.send(
            f"Fehler bei der KI-Anfrage: `{exc}`\n"
            f"Bitte prüfe, ob Ollama läuft (`ollama serve`) und "
            f"`OLLAMA_HOST` in `.env` korrekt gesetzt ist "
            f"(aktuell: `{OLLAMA_HOST}`)."
        )
        return
    except asyncio.TimeoutError:
        await interaction.followup.send(
            "Die Anfrage hat das Zeitlimit überschritten. Versuche es "
            "spaeter erneut oder wechsle das Modell mit `/model`."
        )
        return
    except aiohttp.ClientError as exc:
        log.error("HTTP-Client-Fehler: %s", exc)
        await interaction.followup.send(
            f"Konnte Ollama unter `{OLLAMA_HOST}` nicht erreichen: `{exc}`\n"
            f"Tipp: In `.env` sollte `OLLAMA_HOST=http://127.0.0.1:11434` stehen."
        )
        return

    add_to_history(interaction.channel_id, "user", frage)
    add_to_history(interaction.channel_id, "assistant", answer)

    footer = f"\n\n— _(Antwort mit `{model}`)_"
    for chunk in split_message(answer + footer):
        await interaction.followup.send(chunk)


@ask_group.command(
    name="model",
    description="Zeigt das aktuelle Modell oder wechselt es.",
)
@app_commands.describe(name="Optional: Name des neuen Modells (z. B. qwen3:14b)")
async def model_cmd(
    interaction: discord.Interaction, name: Optional[str] = None
) -> None:
    current = (
        guild_models[interaction.guild_id]
        if interaction.guild_id is not None and interaction.guild_id in guild_models
        else DEFAULT_MODEL
    )

    if name is None:
        # Nur Anzeige
        try:
            available = await ollama.list_models()
        except Exception as exc:
            log.warning("Konnte Modelle nicht auflisten: %s", exc)
            available = []
        listing = (
            "\n".join(f"• `{m}`" for m in available) or "(keine Liste abrufbar)"
        )
        await interaction.response.send_message(
            f"Aktives Modell: **`{current}`**\n\nVerfügbare Modelle:\n{listing}",
            ephemeral=True,
        )
        return

    # Wechsel prüfen
    try:
        available = await ollama.list_models()
    except Exception as exc:
        await interaction.response.send_message(
            f"Fehler beim Abfragen der Modelle: `{exc}`", ephemeral=True
        )
        return

    # Falls die Liste leer ist (z. B. bei Offline-Ollama) tolerant sein
    if available and name not in available:
        await interaction.response.send_message(
            f"Modell `{name}` ist nicht lokal verfügbar.\n"
            f"Verfügbar: " + ", ".join(f"`{m}`" for m in available),
            ephemeral=True,
        )
        return

    if interaction.guild_id is None:
        await interaction.response.send_message(
            "Dieser Befehl kann nur in einem Server verwendet werden.",
            ephemeral=True,
        )
        return

    guild_models[interaction.guild_id] = name
    await interaction.response.send_message(
        f"Modell gewechselt: **`{current}`** → **`{name}`**", ephemeral=False
    )


@ask_group.command(
    name="clear", description="Löscht den Gesprächsverlauf dieses Kanals."
)
async def clear_cmd(interaction: discord.Interaction) -> None:
    channel_id = interaction.channel_id
    if channel_id is None:
        await interaction.response.send_message(
            "Dieser Befehl kann nicht in einer Direktnachricht verwendet werden.",
            ephemeral=True,
        )
        return

    channel_histories[channel_id].clear()
    await interaction.response.send_message(
        "Gesprächsverlauf für diesen Kanal wurde gelöscht.",
        ephemeral=True,
    )


bot.tree.add_command(ask_group)


# ---------------------------------------------------------------------------
# Fehlerbehandlung für Slash-Commands
# ---------------------------------------------------------------------------


@bot.tree.error
async def on_app_command_error(
    interaction: discord.Interaction, error: app_commands.AppCommandError
) -> None:
    log.exception("Slash-Command-Fehler: %s", error)
    if interaction.response.is_done():
        await interaction.followup.send(
            f"Ein Fehler ist aufgetreten: `{error}`", ephemeral=True
        )
    else:
        await interaction.response.send_message(
            f"Ein Fehler ist aufgetreten: `{error}`", ephemeral=True
        )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main() -> None:
    if not DISCORD_TOKEN:
        raise RuntimeError(
            "DISCORD_TOKEN fehlt. Lege eine .env-Datei mit DISCORD_TOKEN=<token> an."
        )
    try:
        await bot.start(DISCORD_TOKEN)
    finally:
        await ollama.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Bot wird beendet (KeyboardInterrupt).")