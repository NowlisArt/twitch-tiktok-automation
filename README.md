# Twitch → TikTok Automation

Dieses Repository gehoert zum Projekt **NowlisArt / TikTok Novel Novel**.

## Bestaetigter Stand

- GitHub Actions: Python-Selbsttest erfolgreich.
- Twitch-Discovery: Die öffentliche Twitch-Clips-Auflistung und Metadatenpruefung funktionieren technisch.
- Die Suche bevorzugt Clips aus den letzten **24 Stunden**, ergaenzt um das 7-Tage-Fenster (nur Clips bis 72 Stunden zulassen).
- Fuer die Vorbereitung sind mindestens 15, maximal 60 Sekunden und mindestens 800 Twitch-Views vorgesehen.
- Die Watchlist enthaelt derzeit **50 statisch gespeicherte Logins**. Sie synchronisiert sich **nicht automatisch** mit TwitchTracker.
- Die Nutzungsrechte wurden vom Nutzer fuer die vorgesehenen Quellen **erklaert, aber nicht unabhaengig verifiziert**.
- Die Vorbereitungs-Pipeline markiert automatische Untertitel als **nicht manuell geprueft**.
- TikTok/Metricool-Autopublishing: **noch nicht eingerichtet oder aktiviert**.

## Workflows

In [Actions](../../actions/workflows/tiktok.yml) den Workflow **Twitch Clip - Safe Self-Test** waehlen:

- **selftest**: Python-Syntax und interne Plausibilitaet.
- **diagnose**: Twitch-Clip-URLs und Metadaten lesen. Kein Videodownload, kein Posting.
- **render-test**: Einen qualifizierten Clip als 9:16-MP4 rendern und fuer die Qualitaetskontrolle als **privates GitHub-Actions-Testartefakt** ablegen. Keine Veroeffentlichung und kein Public Release.

Der normale `push`-Lauf kontrolliert den Code und die Twitch-Quellen. Ein gezielter Testlauf kann zusaetzlich das Rendering pruefen.

## Sicherheitsbedingungen vor der Automatisierung

1. Originaldatum, Aufrufe, Dauer und Twitch-Direktlink pruefen und Duplikate vermeiden.
2. Nutzungsrechte fuer jeden eingesetzten Kanal sicherstellen.
3. Erzeugte Videos visuell kontrollieren: 9:16, Ton, Untertitel, lustige Pointe, Kontext, Hook.
4. Oeffentliche MP4-URLs und Metricool-Planung separat testen, einschliesslich Double-Post-Sperren und Monatslimit.
5. Erst nach bestandenem End-to-End-Test stündliche Vorbereitung und automatisches TikTok-Posting aktivieren.

Automatisches Herunterladen/Rendering/Veröffentlichen von fremden Inhalten ohne gültige Erlaubnis ist nicht zulässig. Zugangsdaten gehoeren nie in Commits; verwende GitHub Secrets.
