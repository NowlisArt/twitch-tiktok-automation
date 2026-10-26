# Stand 26. Oktober 2026

GitHub Actions ist der Starter für Dream Void (@dreamvoid26) und Sunshine (@suhshine28). Die bisherigen ChatGPT-Aufgaben wurden pausiert. Suche und Bearbeitung laufen mit lokalen Werkzeugen und gespeicherter Spracherkennung, ohne laufenden LLM-Aufruf.

## Nachgewiesene Veröffentlichungen

- Sunshine: Bonjwa am 25.10., 19:02 Uhr Berlin: https://www.tiktok.com/@suhshine28/video/7700666931585568033
- Dream Void: automatisch geprüfter Nooreax-Clip am 26.10., 11:03 Uhr Berlin: https://www.tiktok.com/@dreamvoid26/video/7700914545384017185
- Sunshine: automatisch geprüfter Edopeh-Clip am 26.10., 17:02 Uhr Berlin, in Buffers Sent-Ansicht bestätigt: https://www.tiktok.com/@suhshine28/video/7701007290601573665

Die vier älteren Dream-Void-Veröffentlichungen bleiben in der JSON-Belegliste erhalten. Geplante Beiträge zählen erst nach Buffers Status sent als veröffentlicht.

## Automatischer Betrieb

Sechs geplante GitHub-Ausführungen täglich; mögliche Veröffentlichungszeiten je Konto 11, 14, 17, 19 und 21 Uhr Europe/Berlin. Ziel 3–5 verschiedene geeignete Clips pro Konto täglich. Dieses Ziel wurde bisher noch nicht erreicht; ungeeignete Clips werden nicht zur Mengenerfüllung hochgeladen.

Der datierte TwitchTracker-Top-50-Bestand dient als Orientierung; Originalmetadaten stammen von Twitch. Die mündlichen Freigaben sind als Nutzerbestätigung dokumentiert, ohne unabhängige Verifikation zu behaupten.

Neue Clips können ohne Einzelfreigabe veröffentlicht werden, wenn automatische Prüfungen bestehen: technische Medienprüfung, Quellenmetadaten, Rechtebestand, bewegtes Quellbild, lesbare und zeitlich gültige Untertitel sowie lokale ASR-Konsistenz. Diese Annahme ist ausdrücklich maschinell; sie behauptet keine menschliche Wort-für-Wort- oder Kontextprüfung. Manuell abgelehnte exakte Videos bleiben gesperrt.

## Selbstständige Fehlerbehandlung

- Ungeeigneter Kandidat: Fehler speichern und nächsten Kandidaten versuchen.
- Unterbrochene Release-Übertragung: fehlende Dateien ergänzen und vorhandene Bytes abgleichen.
- Temporär nicht abrufbares öffentliches Video: bis zu vier Abrufe mit kurzen Wartezeiten; danach andere Clips weiterbearbeiten und im nächsten Lauf erneut prüfen.
- Unklare Buffer-Antwort nach Übermittlung: dauerhafte Reservierung behalten und später mit der tatsächlichen Queue abgleichen; keine blinde Doppelübermittlung.
- Veröffentlichung: tatsächlichen Providerstatus und TikTok-Link speichern.

Korrektur 2afca3b ist auf main. Lokal bestehen 49 Tests sowie Pipeline- und Verteilungs-Selbsttests. GitHub-Regressionstest 40376067879 ist erfolgreich. Vollständiger Probelauf erfolgreich; ein neuer Clip erstellt und bei temporär fehlender Datei sicher zurückgestellt: https://github.com/NowlisArt/twitch-tiktok-automation/actions/runs/40376156819

## Tatsächlich noch offen

Die Tagesmenge hängt vom Angebot geeigneter Clips und der Providerverfügbarkeit ab. Automatische Routinebehandlung ersetzt keine garantierte Reparatur beliebiger zukünftiger Programmfehler. Bei einer erforderlichen Anmeldung muss der Kontoinhaber eingreifen.

Der bisher festgestellte Buffer-Schlüsselablauf ist der 16. November 2026. Zugang nur direkt unter GitHub Secrets erneuern, keinen Schlüssel im Chat senden. Kein kostenpflichtiger Tarif wurde gebucht.


## Zusätzliche Annahmen durch Buffer, 26. Oktober

- Dream Void, Papaplatte: Buffer-ID 6adf9c873aaff6c7f595cf87, geplant für 21:00 Uhr Berlin.
- Sunshine, Trymacs: Buffer-ID 6adf9cc83faf46bfb54c350b, geplant für 21:00 Uhr Berlin.

Diese beiden Beiträge sind angenommen und geplant, noch nicht als veröffentlicht gezählt. Ihre exakten Medien wurden maschinell geprüft. Der zweite vollständige Versuch wurde am Ende abgebrochen; die zuvor gespeicherten Buffer-IDs und Reservierungen bleiben erhalten.

Fertige Clips werden künftig vor neuer Vorbereitung eingeplant. Die Vorbereitung ist auf zwölf Minuten begrenzt. Der neue manuelle Modus publish prüft und übermittelt nur bereits freigegebene öffentliche Clips, ohne Discovery, Render-Abhängigkeiten oder Spracherkennung erneut zu starten.

Wiederaufnahme ohne Renderarbeit erfolgreich: https://github.com/NowlisArt/twitch-tiktok-automation/actions/runs/40378947995 . 49 Regressionstests erfolgreich; Renderinstallation und ASR übersprungen; sieben Veröffentlichungen und zwei geplante Posts per Live-API bestätigt.
