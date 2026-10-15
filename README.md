# Twitch → TikTok Automation

GitHub-Repository für **NowlisArt** · TikTok über Metricool **Novel Novel** (Brand 7451945).

## Betrieb (16. Oktober 2026)

- GitHub Actions sucht stündlich zwischen 09:17 und 22:17 UTC nach frischen Twitch-Clips.
- Berücksichtigt eine momentan **statische** Liste von 50 deutschen Kanälen in `scripts/pipeline.py`; kein automatischer TwitchTracker-Top-50-Abgleich.
- Genehmigte Kanal-Logins stehen in `config/approved_channels.txt`. Der Nutzer hat eine Wiederveröffentlichungsberechtigung erklärt; dies ist nicht unabhängig geprüft.
- Primär 24 Stunden alt, danach 24–48 Stunden, nur bei besonders starker Performance 48–72 Stunden.
- Mindestdauer der Twitch-Quelle 15 Sekunden, maximale Länge 60 Sekunden, mind. 800 Original-Views. Auswahl bevorzugt über tatsächliche Views/Stunde und Comedy-/Reaktionsindikatoren.
- Erfolgreiche Clips werden auf 9:16 geschnitten, mit Whisper-de Untertiteln versehen, per FFmpeg gerendert, technisch geprüft und als GitHub-Releases bereitgestellt.
- Nach einem Fehler versucht die Pipeline alternative Clips, danach den nächstbesten Kanal. Kürzlich gescheiterte Kandidaten werden sechs Stunden zurückgestellt. Bekannte ungeeignete Tests sind gesperrt.
- Maximal **zwei vorbereitete Videos pro Tag** und **60 pro Monat** als Renderpuffer. Die separate Metricool-Planungsgrenze ist höchstens 20 Posts/Monat.
- `state/auto20.json` enthält Duplikat- und Fehlerhistorie. Bei Nichtverfügbarkeit neuer geeigneter Clips kein Recycling alter Videos.
- **Vorbereitete GitHub-Releases sind NICHT automatisch auf TikTok veröffentlicht.** Die stündliche ChatGPT-Aufgabe kontrolliert die Queue und darf nur nach verifizierter Bild-/Ton-/Untertitel-/Rechte- und Duplikatkontrolle höchstens ein neues Video je Lauf über Metricool planen.
- Automatisch erzeugte Untertitel tragen `subtitle_verified=false` bis zur tatsächlichen Inhaltskontrolle. GitHub `SUCCESS` beweist nur einen technischen Erfolg, nicht Content-Qualität.
- Alle Clips werden soweit möglich auf eigene Hook, verständlichen Inhalt, echte Pointe und gutes Ende geprüft; mangels menschlichem Verständnis der momentanen GitHub-Videoanalyse ist kein viraler Clip und auch keine permanente Clip-Verfügbarkeit garantiert.

## Manuelle Diagnose/Test

[Actions](https://github.com/NowlisArt/twitch-tiktok-automation/actions/workflows/tiktok.yml) erlaubt:
- `selftest`: Python-Syntax + Unit-Selbsttest
- `diagnose`: Original-Twitch-Metadaten lesen
- `render-test`: EINEN Clip nur als GitHub-Artifact für die visuelle Überprüfung rendern, keine TikTok-Veröffentlichung

Der Scheduler bereitet veröffentlichungsfähige **Dateien** vor, ohne TikTok-Aktionen auszulösen. Die ChatGPT-Automation ist ein separater Workflow und muss für jeden neuen Post Qualitätsprüfung und Metricool-Status kontrollieren. Kein automatischer Ersatzclip, wenn die Daten/Rechte unklar sind.

## Kontrollen vor TikTok

Originalalter zum geplanten Veröffentlichungszeitpunkt unter 72 Stunden, Twitch-ID/Slug und Media-URL deduplizieren, Frische, Pointe, Ton, Untertitelinhalt, Grafik/Facecam, Rechte und TikTok-Monatskontingent prüfen. Bei Zweifeln nicht posten.
