/**
 * Deutsche Meldungen.
 *
 * Der Typ ist `Record<MessageKey, string>`: fehlt ein Schlüssel, den
 * `catalog-en.ts` hat, schlägt die Typprüfung fehl — und ein Schlüssel, den es dort
 * nicht gibt, ebenfalls. Die beiden Kataloge können also nicht auseinanderlaufen,
 * ohne dass der Build es sagt.
 *
 * Dies ist die einzige Datei im Repository, die absichtlich deutschen Text
 * enthält; alles andere — Quelltext, Kommentare, Dokumentation, Servermeldungen —
 * ist englisch.
 */

import type { MessageKey } from "./catalog-en";

export const de: Record<MessageKey, string> = {
  // ── Gemeinsames ────────────────────────────────────────────────────────────
  "common.cancel": "Abbrechen",
  "common.save": "Speichern",
  "common.saving": "Speichert…",
  "common.close": "Schließen",
  "common.delete": "Löschen",
  "common.pleaseWait": "Bitte warten…",
  "common.pending": "Ausstehend",
  "common.unknown": "Unbekannt",
  "common.days_one": "{count} Tag",
  "common.days_other": "{count} Tage",

  // ── Sprachumschalter ───────────────────────────────────────────────────────
  "lang.label": "Sprache",
  "lang.switchTo": "Auf {language} umstellen",

  // ── Seitenleiste ───────────────────────────────────────────────────────────
  "sidebar.menu": "Menü",
  "sidebar.general": "Allgemein",
  "sidebar.overview": "Übersicht",
  "sidebar.explorer": "Datenexplorer",
  "sidebar.quality": "Datenqualität",
  "sidebar.analysis": "Analysen",
  "sidebar.chat": "KI-Chat",
  "sidebar.connectors": "Connectors",
  "sidebar.docs": "Dokumentation",
  "sidebar.docsTitle": "Zentrale Plattform-Dokumentation öffnen",
  "sidebar.settings": "Einstellungen",
  "sidebar.logout": "Abmelden",

  // ── Kopfzeile ──────────────────────────────────────────────────────────────
  "header.docs": "Dokumentation",
  "header.refresh": "Aktualisieren",
  "header.refreshTitle": "Gesamte Seite neu laden",
  "header.addConnector": "Connector hinzufügen",

  // ── Rechtliches ────────────────────────────────────────────────────────────
  "footer.nav": "Rechtliches und Dokumentation",
  "footer.imprint": "Impressum",
  "footer.privacy": "Datenschutzerklärung",
  "footer.docs": "Dokumentation",
  "footer.source": "Quellcode",
  "footer.sourceVersion": "Quellcode (v{version})",
  "footer.sourceCommit": "Quellcode ({commit})",
  "legal.nav": "Rechtliches",
  "legal.backToApp": "Zurück zur Anwendung",
  "legal.disclaimer":
    "Diese Texte sind eine Vorlage und ersetzen keine Rechtsberatung. Vor dem produktiven Einsatz durch eine qualifizierte Stelle prüfen lassen.",
  "legal.translationNote":
    "Dies ist eine Übersetzung als Lesehilfe. Verbindlich ist die deutsche Fassung.",

  // ── Anmeldung ──────────────────────────────────────────────────────────────
  "auth.tagline": "Deine persönliche Gesundheits- und Analyse-Plattform.",
  "auth.welcomeBack": "Willkommen zurück",
  "auth.createAccount": "Konto erstellen",
  "auth.name": "Name",
  "auth.email": "E-Mail",
  "auth.password": "Passwort",
  "auth.signIn": "Anmelden",
  "auth.signUp": "Konto registrieren",
  "auth.noAccount": "Noch kein Konto?",
  "auth.haveAccount": "Bereits registriert?",
  "auth.toSignUp": "Jetzt registrieren",
  "auth.toSignIn": "Hier anmelden",
  "auth.registrationClosed": "Neuregistrierung vom Administrator deaktiviert.",
  "auth.or": "oder",
  "auth.redirecting": "Weiterleitung…",
  "auth.signInWith": "Mit {provider} anmelden",
  "auth.providerUnavailable": "Anmeldung über diesen Anbieter ist nicht möglich.",
  "auth.failed": "Authentifizierung fehlgeschlagen",
  "auth.useExistingAccount": "Stattdessen mit dieser E-Mail-Adresse anmelden.",
  "auth.callbackWorking": "Anmeldung wird abgeschlossen…",
  "auth.callbackFailed": "Die Anmeldung konnte nicht abgeschlossen werden.",
  "auth.callbackRetry": "Zurück zur Anmeldung",

  // ── Sign-in callback ────────────────────────────────────────────────────
  "auth.callbackTitle": "Anmeldung fehlgeschlagen",
  "auth.callbackDone": "Angemeldet. Weiterleitung…",
  "auth.callbackIncomplete": "Die Rückmeldung des Anbieters war unvollständig.",

  // ── System warnings ─────────────────────────────────────────────────────
  "warnings.region": "Systemwarnungen",
  "warnings.severity.critical": "Kritisch",
  "warnings.severity.warning": "Warnung",
  "warnings.severity.info": "Hinweis",
  "warnings.openDocs": "Dokumentation öffnen",
  "warnings.dismiss": "Für einen Tag ausblenden",
  "warnings.dismissTitle": "Für einen Tag ausblenden — morgen wieder da, bis es behoben ist",
  "warning.password_published.title": "Dieses Passwort ist öffentlich bekannt",
  "warning.password_published.detail":
    "Der Hash dieses Passworts stand in einer veröffentlichten Quelle — es war der Entwicklungs-Zugang, den frühere Versionen dieses Projekts mitgeliefert haben. bcrypt verzögert einen Angriff, es verhindert ihn nicht. Wer den Hash hat, kann das Passwort offline durchprobieren, so lange er möchte.",
  "warning.password_published.action":
    "Passwort jetzt ändern — und falls es anderswo verwendet wird, dort ebenfalls.",
  "warning.insecure_jwt_secret.title": "JWT_SECRET ist ein veröffentlichter Standardwert",
  "warning.insecure_jwt_secret.detail":
    "Sitzungen werden mit einem Schlüssel signiert, der im Quellcode dieses Projekts steht. Wer ihn kennt, kann sich ein Token für jedes Konto und jeden Arbeitsbereich ausstellen.",
  "warning.insecure_jwt_secret.action": "Einen eigenen Wert setzen: {generate}",
  "warning.insecure_encryption_key.title": "ENCRYPTION_KEY ist ein veröffentlichter Standardwert",
  "warning.insecure_encryption_key.detail":
    "Die hinterlegten Connector-Zugangsdaten sind für jeden entschlüsselbar, der diesen Schlüssel kennt — und er steht im Quellcode.",
  "warning.insecure_encryption_key.action":
    "Erst umschlüsseln, dann umstellen: python -m core.rotate_encryption_key --old … --new … Ein Wechsel ohne diesen Schritt macht alle gespeicherten Tokens dauerhaft unlesbar.",
  "warning.insecure_internal_secret.title":
    "INTERNAL_SERVICE_SECRET ist ein veröffentlichter Standardwert",
  "warning.insecure_internal_secret.detail":
    "Damit kann sich jeder als interner Dienst ausweisen und entschlüsselte Connector-Zugangsdaten abrufen.",
  "warning.insecure_internal_secret.action": "Einen eigenen Wert setzen: {generate}",
  "warning.registration_open.title": "Selbstregistrierung ist offen",
  "warning.registration_open.detail":
    "Jede Person, die diese Adresse kennt, kann sich ein Konto und einen eigenen Arbeitsbereich anlegen.",
  "warning.registration_open.action":
    "ALLOW_REGISTRATION=false setzen. Das erste Konto legt python -m core.create_owner an.",
  "warning.cookies_not_secure.title": "Sitzungs-Cookies ohne Secure-Flag",
  "warning.cookies_not_secure.detail":
    "Die Cookies werden auch über unverschlüsselte Verbindungen gesendet und sind dort mitlesbar.",
  "warning.cookies_not_secure.action":
    "COOKIE_SECURE=true setzen. Für lokale Entwicklung ist das unproblematisch: Browser behandeln localhost und 127.0.0.1 als vertrauenswürdig und akzeptieren Secure-Cookies dort.",
  "warning.development_environment.title": "ENVIRONMENT ist „{environment}“",
  "warning.development_environment.detail":
    "Deshalb starten die Dienste trotz der obigen Punkte. Mit einem produktiven ENVIRONMENT verweigern Core und Gateway den Start, solange ein Wert ein veröffentlichter Standard ist.",
  "warning.development_environment.action":
    "Für ein echtes Deployment ENVIRONMENT=production setzen.",

  // ── Overview ────────────────────────────────────────────────────────────
  "overview.title": "Übersicht",
  "overview.subtitle": "Aggregierte Auswertung deiner verbundenen Sensoren und Tracker.",
  "overview.empty": "Noch keine Datenpunkte gespeichert.",
  "overview.emptyAction": "Quelle verbinden und Daten importieren",
  "overview.loadingChart": "Diagramm lädt…",
  "overview.loadingMap": "Karte lädt…",
  "header.welcome": "Willkommen zurück, {name}",

  // ── Data quality ────────────────────────────────────────────────────────
  "quality.eyebrow": "Datenqualität",
  "quality.title": "Datenqualität",
  "quality.subtitle":
    "Finde Lücken, Quellenkonflikte und konkrete nächste Schritte für belastbare Analysen.",
  "quality.window": "Zeitfenster",
  "quality.windowDays": "{count} Tage",
  "quality.gapsTitle": "Datenlücken",
  "quality.gapsDetail": "{metrics} Metriken im {days}-Tage-Fenster",
  "quality.conflictsTitle": "Quellenkonflikte",
  "quality.conflictsDetail": "Abweichungen über 5 %",
  "quality.conflictsNone": "Keine auffälligen konkurrierenden Quellen.",
  "quality.conflictsHelp": "Einheiten und bevorzugte Primärquelle prüfen.",
  "quality.recommendationComplete": "Datenbasis wirkt vollständig.",
  "quality.recommendationMinor": "Leichte Lücken: Analyse nutzbar, aber Trends prüfen.",
  "quality.recommendationSerious":
    "Connector, Token oder Sync-Frequenz prüfen, bevor Empfehlungen abgeleitet werden.",
  "quality.explainTitle": "Was bedeuten diese Werte?",
  "quality.explainBody":
    "Lücken reduzieren die Aussagekraft von Trends und Korrelationen. Quellenkonflikte zeigen, dass zwei Integrationen für denselben Zeitraum unterschiedliche Werte liefern. Empfehlung: zuerst Datenqualität stabilisieren, dann Korrelationen interpretieren.",
  "quality.explainDocs": "Dokumentation zur Datenqualität",
  "quality.interruptionsTitle": "Unterbrechungen",
  "quality.interruptionsHint":
    "Fortlaufend aufgezeichnete Metriken — Puls, Wetter — gemessen an der tatsächlich eingehaltenen Rate statt an Kalendertagen.",
  "quality.unsupportedTitle": "Noch nicht unterstützt",
  "quality.unsupportedHint":
    "Dein Gerät sendet diese Felder, und diese Plattform speichert sie noch nicht. Erfasst sind ausschließlich Feldnamen und Typen — nie ein Wert.",
  "quality.unsupportedConnector": "Connector",
  "quality.unsupportedField": "Feld",
  "quality.unsupportedKind": "Typ",
  "quality.unsupportedSeen": "Gesehen",
  "quality.unsupportedLastSeen": "Zuletzt",
  "quality.unsupportedCopy": "Bericht kopieren",
  "quality.unsupportedCopied": "Kopiert",
  "quality.quarantineTitle": "Für deine Entscheidung zurückgehalten",
  "quality.quarantineHint":
    "Diese Werte bleiben außerhalb von Diagrammen und Analysen, bis du den Connector-Namen zuordnest, übernimmst, verwirfst oder offen lässt.",
  "quality.quarantineCapacityTitle": "Quarantänekapazität",
  "quality.quarantineCapacityIntro":
    "Unbekannte Werte werden hier für die Zuordnung zurückgehalten. Löse sie auf, bevor der Connector sein Limit erreicht; Werte nach einem vollen Limit können später nicht durch ein Mapping wiederhergestellt werden.",
  "quality.quarantineCapacityPending":
    "Unbekannte Werte warten auf eine Entscheidung. Löse sie vor dem nächsten großen Import auf, damit die Quarantäne Platz für neue Werte hat.",
  "quality.quarantineCapacityHalf":
    "Die Quarantäne ist zu {percent} % ausgelastet. Wenn das Limit erreicht ist, werden weitere unbekannte Werte nicht behalten und können später nicht zugeordnet werden.",
  "quality.quarantineCapacityNearFull":
    "Die Quarantäne ist zu {percent} % ausgelastet. Löse diesen Connector jetzt auf: Weitere unbekannte Werte können bald abgewiesen werden und für die spätere Zuordnung verloren gehen.",
  "quality.quarantineCapacityFull":
    "Das Quarantänelimit ist voll. Weitere unbekannte Werte werden nicht behalten und können durch ein späteres Mapping dieses Connectors nicht wiederhergestellt werden.",
  "quality.quarantineCapacityRefused":
    "Für diesen Connector wurden bereits unbekannte Werte abgewiesen. Sie befinden sich nicht in der Quarantäne; importiere die Quelle nach der Zuordnung erneut.",
  "quality.quarantineCapacityUsage":
    "Zurückgehaltene Punkte: {rows} / {maxRows} · Unbekannte Namen: {names} / {maxNames}",
  "quality.quarantineConnectorDetail": "{connector} · {count} Punkt(e)",
  "quality.mappingDecision": "Zuordnungsentscheidung",
  "quality.mappingMap": "Einem Registry-Metrik zuordnen",
  "quality.mappingAdopt": "Als eigene Metrik übernehmen",
  "quality.mappingDiscard": "Verwerfen und weiter verwerfen",
  "quality.mappingKeep": "Ungeklärt behalten",
  "quality.mappingTarget": "Zielmetrik",
  "quality.mappingCustomName": "custom_metric_name",
  "quality.mappingSourceUnit": "Quelleneinheit",
  "quality.mappingTargetUnit": "Angegebene Einheit",
  "quality.mappingAggregation": "Aggregation",
  "quality.mappingCadence": "Frequenz",
  "quality.mappingAverage": "Durchschnitt",
  "quality.mappingSum": "Summe",
  "quality.mappingLast": "Letzter Wert",
  "quality.mappingMax": "Maximum",
  "quality.mappingDaily": "Täglich",
  "quality.mappingContinuous": "Kontinuierlich",
  "quality.mappingEvent": "Ereignis",
  "quality.mappingApply": "Anwenden und wiedergeben",
  "quality.mappingSaving": "Wird angewendet…",
  "quality.mappingKeepIndefinitely": "Ungeklärte Werte unbegrenzt behalten",
  "quality.largestGaps": "Größte Datenlücken",
  "quality.largestGapsHint":
    "Zusammenhängende fehlende Tage. Über „Nachladen“ wird der Importdialog mit genau diesem Zeitraum vorbelegt.",
  "quality.noGaps": "Keine Datenlücken im {days}-Tage-Fenster gefunden.",
  "quality.moreRanges": "… und {count} weitere Bereiche",
  "quality.backfillTitle": "Fehlende Daten nachladen",
  "quality.backfillSource": "{source} nachladen",
  "quality.backfillHint":
    "Der Importdialog schlägt den benötigten Zeitraum vor und überspringt bereits vorhandene Bereiche.",
  "quality.conflictsNoneLong": "Keine widersprüchlichen Messwerte gefunden.",
  "quality.conflictsSome": "{count} Messwerte weichen zwischen Quellen deutlich voneinander ab.",
  "quality.conflictsAdvice":
    "Bei Konflikten sollte die zuverlässigste Quelle pro Metrik priorisiert und die Einheit im Importer-Transformer geprüft werden.",

  // ── Charts and map ──────────────────────────────────────────────────────
  "chart.calories": "Kalorien (kcal)",
  "chart.protein": "Protein (g)",
  "chart.carbs": "Kohlenhydrate (g)",
  "chart.fat": "Fett (g)",
  "chart.sleepScore": "Sleep Score",
  "chart.readinessScore": "Readiness Score",
  "chart.categoryNutrition": "Ernährung",
  "chart.categoryBio": "Schlaf & Bio-Scores",
  "chart.period": "Zeitraum:",
  "chart.presetAll": "Gesamt",
  "chart.presetCustom": "Datum…",
  "chart.rangeTo": "bis",
  "chart.typeArea": "Flächendiagramm",
  "chart.typeLine": "Liniendiagramm",
  "chart.typeBar": "Balkendiagramm",
  "chart.refresh": "Diagramm aktualisieren",
  "chart.emptyPeriod": "Keine Datenpunkte für den ausgewählten Zeitraum vorhanden.",
  "chart.emptyFilter": "Keine Datenpunkte für die aktuelle Filterauswahl vorhanden.",
  "map.tilesFailed":
    "Die Karte konnte nicht geladen werden. Es wird die Vektor-Darstellung verwendet.",
  "map.today": "Heute",
  "map.showTiles": "Karte laden",
  "map.hideTiles": "Karte ausblenden",
  "map.showTilesTitle": "Lädt Kartenkacheln von einem externen Anbieter",
  "map.hideTilesTitle": "Zurück zur Vektor-Darstellung",
  "map.privacyLead":
    "Es werden keine Standortdaten an Kartenanbieter übertragen. Beim Laden der Kacheln wird der betrachtete Kartenausschnitt für den Anbieter sichtbar.",
  "map.empty": "Keine GPS-Punkte im gewählten Zeitraum.",

  // ── Map privacy detail ──────────────────────────────────────────────────
  "map.privacyDetail":
    "Es werden keine Standortdaten an Kartenanbieter übertragen. Beim Laden der Karte fordert dein Browser Kacheln direkt beim Anbieter an; dabei wird der betrachtete Kartenausschnitt für den Anbieter sichtbar.",
  "map.headline": "GPS-Standorte & Strecke",

  // ── Metric cards ────────────────────────────────────────────────────────
  "cards.range": "Spanne: {min} – {max} {unit}",

  // ── Connectors ──────────────────────────────────────────────────────────
  "connectors.title": "Connectors",
  "connectors.subtitle":
    "Verwalte deine Datenquellen und Zugangsdaten und beobachte den Event-Broker live.",
  "connectors.desc.yazio":
    "Kalorien, Makronährstoffe (Protein, Kohlenhydrate, Fett) und Mahlzeitentagebuch.",
  "connectors.desc.dawarich":
    "GPS-Standortdaten und Bewegungsstrecken, gespeichert mit PostGIS-Spatial-Index.",
  "connectors.desc.whoop": "Herzfrequenzvariabilität, Schlafphasen und Strain Score.",
  "connectors.desc.apple_health":
    "Schritte, Aktivitätsenergie, Ruheherzfrequenz und Schlafphasen über Health Auto Export.",
  "connectors.desc.streak":
    "Krafttraining aus Streak 2.0: Übungen, Sätze, Wiederholungen und Gewicht.",
  "connectors.desc.home_assistant": "Temperatur, Luftfeuchte, Licht- und Geräuschsensoren.",
  "connectors.desc.weather": "Temperatur, Luftdruck, Niederschlag und UV-Index.",
  "connectors.desc.calendar": "ICS-Feeds, Termine, Meetingdauer und Busy Hours pro Tag.",
  "connectors.nameWeather": "Wetter",
  "connectors.nameCalendar": "Kalender",
  "connectors.confirmDelete":
    "Die Anbindung zu {source} und die dort gespeicherten Zugangsdaten wirklich löschen?",
  "connectors.passive": "Passiver Connector",
  "connectors.active": "Aktiver Connector",
  "connectors.passiveHint": "Passiv · empfängt Daten",
  "connectors.activeHint": "Aktiv · fragt den Dienst ab",
  "connectors.soon": "Demnächst",
  "connectors.openDocs": "Dokumentation öffnen",
  "connectors.syncFailed": "Letzter Lauf fehlgeschlagen",
  "connectors.disconnect": "Connector trennen und löschen",
  "connectors.connectNow": "Jetzt verknüpfen",
  "connectors.loadingDetails": "Connector- und Queue-Details laden…",
  "connectors.colSource": "Verbindung / Quelle",
  "connectors.colTransfer": "Datenübertragung",
  "connectors.everyHours": "Alle {hours} Std. ({days} Tage Lookback)",
  "connectors.edit": "Bearbeiten",
  "connectors.emptyList": "Noch keine Connectors konfiguriert.",
  "connectors.addFirst": "Ersten Connector hinzufügen",

  // ── Connector state ─────────────────────────────────────────────────────
  "connectors.ready": "Bereit",

  // ── Connector actions ───────────────────────────────────────────────────
  "connectors.import": "Importieren",
  "connectors.upload": "Hochladen",
  "connectors.fileDriven": "Wird per Export-Datei befüllt",
  "connectors.queued": "In Warteschlange",
  "connectors.newConnector": "Neuer Connector",
  "connectors.docs": "Doku",
  "connectors.processing": "Event in Warteschlange (wird verarbeitet)",
  "connectors.readyActive": "Bereit / aktiv",
  "connectors.webhookDriven": "Webhook · ereignisbasiert",
  "connectors.tableTitle": "Konfigurierte Verbindungen & Live-Queue-Status",
  "connectors.autoRefresh": "Aktualisiert alle {seconds}s",
  "connectors.configuredCount_one": "{count} Connector konfiguriert",
  "connectors.configuredCount_other": "{count} Connectoren konfiguriert",
  "connectors.colQueue": "NATS-Queue & Status",
  "connectors.colLastSync": "Letzter Sync",
  "connectors.colActions": "Aktionen",
  "connectors.addAnother": "Weiteren hinzufügen",
  "connectors.instanceCount_one": "{count} eingerichtet",
  "connectors.instanceCount_other": "{count} eingerichtet",
  "connectors.tabs": "Connector-Ansichten",
  "connectors.tabCurrent": "Aktuelle Importer",
  "connectors.tabAvailable": "Importer hinzufügen",
  "connectors.availableHint": "Wähle eine Datenquelle für diesen Workspace aus.",
  "connectors.details": "Läufe",
  "connectors.openDetails": "Details zu den Importer-Läufen öffnen",

  // ── Importer detail page ───────────────────────────────────────────────
  "importerDetail.eyebrow": "Importer-Details",
  "importerDetail.back": "Zurück zu den Connectors",
  "importerDetail.backToConnectors": "Zurück zu den Connectors",
  "importerDetail.notFound": "Connector nicht gefunden",
  "importerDetail.notFoundHint": "Dieser Connector ist im aktuellen Workspace nicht konfiguriert.",
  "importerDetail.totalRuns": "Läufe insgesamt",
  "importerDetail.successfulRuns": "Erfolgreich",
  "importerDetail.failedRuns": "Fehlgeschlagen",
  "importerDetail.activeRuns": "Aktiv",
  "importerDetail.typicalDuration": "Übliche Dauer",
  "importerDetail.latestRun": "Letzter Lauf",
  "importerDetail.status": "Status",
  "importerDetail.trigger": "Auslöser",
  "importerDetail.started": "Gestartet",
  "importerDetail.finished": "Beendet",
  "importerDetail.duration": "Dauer",
  "importerDetail.mode": "Modus",
  "importerDetail.modeSmart": "Smart",
  "importerDetail.modeForce": "Force",
  "importerDetail.modeOther": "Sonstiger",
  "importerDetail.requestId": "Request-ID",
  "importerDetail.historyTitle": "Vollständige Laufhistorie",
  "importerDetail.autoRefresh": "Aktualisiert alle {seconds}s",
  "importerDetail.loading": "Laufhistorie wird geladen…",
  "importerDetail.loadingMore": "Weitere werden geladen…",
  "importerDetail.loadMore": "Ältere Läufe laden",
  "importerDetail.historyFailed": "Die Laufhistorie konnte nicht geladen werden.",
  "importerDetail.noRuns": "Bisher wurden keine Importläufe aufgezeichnet.",
  "importerDetail.noDuration": "Noch nicht beendet",
  "importerDetail.durationSeconds": "{count} s",
  "importerDetail.durationMinutes": "{count} Min.",
  "importerDetail.points": "{accepted} akzeptiert · {duplicate} Duplikate · {expected} erwartet",
  "importerDetail.unknown": "unbekannt",
  "importerDetail.statusSuccess": "Erfolgreich",
  "importerDetail.statusError": "Fehlgeschlagen",
  "importerDetail.statusSkipped": "Übersprungen",
  "importerDetail.statusQueued": "Eingereiht",
  "importerDetail.statusRunning": "Läuft",
  "importerDetail.statusUnknown": "Unbekannt",
  "importerDetail.triggerScheduled": "Geplant",
  "importerDetail.triggerManual": "Manuell",
  "importerDetail.triggerPush": "Push",
  "importerDetail.triggerUpload": "Upload",
  "importerDetail.triggerOther": "Sonstiger",

  // ── API keys and external sign-in ───────────────────────────────────────
  "apikeys.loadFailed": "Schlüssel konnten nicht geladen werden.",
  "apikeys.createFailed": "Schlüssel konnte nicht erstellt werden.",
  "apikeys.confirmRevoke":
    "Schlüssel {prefix}… wirklich widerrufen? Geräte, die ihn verwenden, können danach sofort keine Daten mehr senden.",
  "apikeys.copyFailed": "Kopieren nicht möglich — bitte manuell markieren.",
  "apikeys.headerHint":
    "Ein separater X-Tenant-ID-Header ist nicht nötig — der Tenant wird aus dem Schlüssel selbst ermittelt. Ältere Apps dürfen weiterhin X-Api-Key senden.",
  "apikeys.docs": "Dokumentation zu API-Keys",
  "apikeys.shownOnce": "Dieser Schlüssel wird nur einmal angezeigt",
  "apikeys.copy": "In die Zwischenablage kopieren",
  "apikeys.storeNow":
    "Jetzt in der App hinterlegen. Nach dem Schließen ist er nicht wieder abrufbar — nur widerrufen und neu erzeugen.",
  "apikeys.none": "Noch kein Schlüssel für {provider}. Erzeuge einen, um Daten zu empfangen.",
  "apikeys.created": "Erstellt {date}",
  "apikeys.expires": "läuft ab {date}",
  "apikeys.lastUsed": "zuletzt genutzt {date}",
  "apikeys.neverUsed": "noch nie genutzt",
  "apikeys.statusActive": "aktiv",
  "apikeys.statusRevoked": "widerrufen",
  "apikeys.rotateTitle": "Nachfolger erzeugen; dieser Key bleibt bis zum Widerruf gültig",
  "apikeys.revokeTitle": "Sofort ungültig machen",
  "apikeys.namePlaceholder": "z. B. iPhone",
  "apikeys.noExpiry": "Kein Ablauf",
  "apikeys.rotationHint":
    "Mehrere aktive Schlüssel sind vorgesehen: so lässt sich rotieren, ohne dass die Datenübertragung unterbrochen wird. Den alten erst widerrufen, wenn die",
  "oidc.forbidden": "Nur Inhaber und Administratoren können Anbieter verwalten.",
  "oidc.loadFailed": "Anbieter konnten nicht geladen werden.",
  "oidc.saveFailed": "Speichern fehlgeschlagen.",
  "oidc.deleteFailed": "Löschen fehlgeschlagen.",
  "oidc.title": "Externe Anmeldeanbieter",
  "oidc.subtitle": "OpenID Connect. Anbieter sind standardmäßig deaktiviert.",
  "oidc.add": "Anbieter hinzufügen",
  "oidc.loading": "Anbieter werden geladen…",
  "oidc.enabled": "aktiv",
  "oidc.hasSecret": "Client Secret hinterlegt",
  "oidc.noSecret": "Kein Client Secret (Public Client)",
  "oidc.editing": "{slug} bearbeiten",
  "oidc.newProvider": "Neuer Anbieter",
  "oidc.fieldSlug": "Slug (URL-Teil)",
  "oidc.fieldDisplayName": "Anzeigename",
  "oidc.fieldIssuer": "Issuer",
  "oidc.fieldClientId": "Client ID",
  "oidc.fieldClientSecret": "Client Secret",
  "oidc.fieldRedirectUri": "Redirect URI",
  "oidc.fieldScopes": "Scopes",
  "oidc.secretUnchanged": "•••••••• (unverändert lassen)",
  "oidc.toggleEnabled": "Aktiv",
  "oidc.toggleEnabledHint": "Erscheint auf der Anmeldeseite.",

  // ── Profile and import ──────────────────────────────────────────────────
  "profile.subtitle":
    "Verwalte deine Benutzerdaten, Sicherheitseinstellungen und die 1-Klick-Datenlöschung.",
  "profile.passwordMismatch": "Die neuen Passwörter stimmen nicht überein.",
  "profile.passwordFailed": "Passwortänderung fehlgeschlagen.",
  "profile.passwordChanged": "Passwort geändert.",
  "profile.wipeFailed": "Datenpunkt-Reset fehlgeschlagen.",
  "profile.wipeDone": "{count} Datenpunkte im Workspace gelöscht.",
  "profile.deleteAccountFailed": "Kontolöschung fehlgeschlagen.",
  "profile.gdprTitle": "1-Klick-Datenlöschung (DSGVO Art. 17)",
  "profile.gdprBadge": "Löschrecht aktiv",
  "profile.gdprBody":
    "Gemäß DSGVO Art. 17 (Recht auf Vergessenwerden) kannst du alle gespeicherten Datenpunkte oder dein Konto vollständig mit einem Klick löschen.",
  "profile.wipeButton": "Alle Datenpunkte löschen",
  "profile.deleteAccountButton": "Konto und alle Daten löschen",
  "profile.changePassword": "Passwort ändern",
  "profile.confirm": "Bestätigen",
  "profile.changing": "Wird geändert…",
  "profile.encryptionNote":
    "Connector-Tokens werden vor der Speicherung mit Fernet AES-256 verschlüsselt.",
  "profile.signOut": "Vom Konto abmelden",
  "profile.wipeConfirmTitle": "Alle Datenpunkte löschen?",
  "profile.wipeConfirmBody":
    "Damit werden alle importierten Datenpunkte in deinem Workspace gelöscht.",
  "profile.wipeConfirmAction": "Ja, alle Datenpunkte löschen",
  "profile.wipeRunning": "Lösche Daten…",
  "profile.deleteAccountTitle": "Vollständige Kontolöschung?",
  "profile.deleteAccountBody":
    "Dieser Vorgang löscht alle Datenpunkte, Connector-Tokens und Freigaben deines Kontos unwiderruflich (DSGVO Art. 17).",
  "profile.deleteAccountAction": "Unwiderruflich löschen",
  "profile.deleteAccountRunning": "Lösche Konto…",
  "profile.privacyLead":
    "Welche Daten verarbeitet werden, auf welcher Grundlage und wie du sie löschen kannst",
  "import.days": "{count} Tage",
  "import.title": "Daten importieren — {name}",
  "import.from": "Von",
  "import.to": "Bis",
  "import.suggestion": "Vorschlag:",
  "import.modeLegend": "Modus",
  "import.smartLabel": "Smart (empfohlen)",
  "import.forceBody": "Der gesamte Zeitraum wird erneut verarbeitet.",
  "import.forceWarning":
    "Force-Importe verursachen deutlich mehr Verarbeitungsaufwand und erzeugen doppelte Events. Doppelte Datenpunkte entstehen dank Idempotenz trotzdem nicht,",
  "import.previewLegend": "Vorschau",
  "import.howItWorks": "Wie Smart- und Force-Import funktionieren",
  "import.recent": "Letzte Importe ({count})",
  "import.runCounts": "{accepted} neu · {duplicate} Duplikate",
  "import.running": "Import läuft",
  "import.progressOf": "{done} von {total} Datenpunkten gespeichert",
  "import.progressCounted": "{count} Datenpunkte bisher gespeichert",
  "import.typicallySeconds": "dauert üblicherweise etwa {count} s",
  "import.typicallyMinutes": "dauert üblicherweise etwa {count} min",
  "import.passiveExplainer":
    "Dieser Connector empfängt Daten, wenn dein Gerät sie sendet — hier gibt es also nichts anzustoßen. Was ein Push-Import trotzdem hat, steht darunter: wie weit der laufende gekommen ist und was frühere getan haben.",
  "import.uploadLegend": "Export-Datei importieren",
  "import.uploadHintAppleHealth":
    "In der Health-App dein Profil öffnen und „Alle Gesundheitsdaten exportieren“ wählen. Die export.zip, die du bekommst, hier hochladen — sie enthält deine gesamte Historie, Workouts und GPS-Routen inklusive.",
  "import.uploadHintWhoop":
    "In der Whoop-App unter Account den Datenexport anfordern. Das ZIP mit den CSV-Dateien, das per E-Mail kommt, hier hochladen.",
  "import.uploadChoose": "Export-Datei auswählen",
  "import.uploadStart": "Hochladen",
  "import.uploading": "Wird hochgeladen…",
  "import.uploadProgress": "Upload-Fortschritt",
  "import.uploadProgressPercent": "{percent} % hochgeladen",
  "import.uploadAccepted":
    "Die Datei ist angekommen und wird gelesen. Der Fortschritt erscheint oben.",
  "import.uploadFailed": "Die Datei konnte nicht hochgeladen werden.",
  "import.uploadInParts":
    "Die Datei wird in Teilen gesendet, damit auch ein großer Export durchkommt. Du kannst diesen Dialog schließen — der Upload läuft weiter.",
  "import.minimize": "Minimieren",
  "import.minimizeHint": "Dialog schließen. Der Upload läuft weiter und bleibt sichtbar.",
  "import.uploadReimportNote":
    "Dieselbe Datei kann erneut hochgeladen werden, ohne Duplikate zu erzeugen: ein bereits gespeicherter Messwert bleibt ein Messwert.",
  "import.planFailed": "Importplan konnte nicht geladen werden.",
  "import.startFailed": "Import konnte nicht gestartet werden.",
  "import.nothingToDo": "Nichts zu tun — der Zeitraum ist bereits vollständig vorhanden.",
  "import.queued": "Import wurde eingereiht.",
  "import.subtitle": "Zeitraum prüfen und anpassen, bevor der Import startet.",
  "import.close": "Dialog schließen",
  "import.smartHint": "Bereits vollständig vorhandene Zeiträume werden übersprungen. Nur der",
  "import.forceLabel": "Alles erzwingen",
  "import.forceHint":
    "aber der Lauf dauert länger und belastet das API-Kontingent des Anbieters. Der Lauf wird im Importprotokoll als force gekennzeichnet.",
  "import.noAnalysis": "Noch keine Analyse verfügbar.",
  "import.tooIrregular": "Die vorhandenen Daten sind zu unregelmäßig für eine sichere",
  "import.willSkip": "Wird übersprungen",
  "import.willImport": "Wird importiert",
  "import.nothingToImportShort": "Nichts zu importieren.",
  "import.start": "Import starten",
  "import.nothingToImport": "Nichts zu importieren",

  // ── Upload-Banner (ein Upload, der seinen Dialog überlebt hat) ──────────────
  "upload.title": "Upload läuft — {name}",
  "upload.doneTitle": "Upload abgeschlossen — {name}",
  "upload.errorTitle": "Upload fehlgeschlagen — {name}",
  "upload.cancelledTitle": "Upload abgebrochen — {name}",
  "upload.sentOf": "{done} von {total} MB · {percent} %",
  "upload.progressPercent": "{percent} % hochgeladen",
  "upload.assembling": "Alle Teile sind angekommen. Der Importer liest das Archiv…",
  "upload.doneBody": "Das Archiv wird gelesen. Der Connector zeigt, wie der Import läuft.",
  "upload.errorBody": "Der Upload ist abgebrochen, bevor die Datei vollständig war.",
  "upload.cancelledBody": "Die bereits angekommenen Teile wurden gelöscht.",
  "upload.cancel": "Upload abbrechen",
  "upload.resume": "Fortsetzen",
  "upload.dismiss": "Ausblenden",

  // ── Import duration ─────────────────────────────────────────────────────
  "import.hours": "{count} Std.",

  // ── Data explorer ───────────────────────────────────────────────────────
  "explorer.title": "Rohdaten-Explorer",
  "explorer.subtitle":
    "Direkter Zugriff auf alle Rohdatenpunkte dieses Workspace. Gespeicherte Ansichten liegen in PostgreSQL.",
  "explorer.refresh": "Daten aktualisieren",
  "explorer.savedViews": "Gespeicherte Ansichten",
  "explorer.saveCurrent": "Aktuelle Ansicht speichern",
  "explorer.viewNamePlaceholder": "Name der Ansicht…",
  "explorer.deleteView": "Ansicht löschen",
  "explorer.noViews":
    "Noch keine gespeicherten Ansichten. Filter einstellen und auf „Aktuelle Ansicht speichern“ klicken.",
  "explorer.source": "Quelle:",
  "explorer.allSources": "Alle Quellen",
  "explorer.period": "Zeitraum:",
  "explorer.aggregation": "Aggregat:",
  "explorer.dailySum": "Tages-Summe",
  "explorer.dailyAverage": "Tages-Durchschnitt",
  "explorer.dailyMax": "Tages-Maximum",
  "explorer.selectAll": "Alle auswählen",
  "explorer.searchPlaceholder":
    "Volltextsuche in Rohdaten (Lebensmittelname, Kategorie, Metrik-Name oder JSON-Metadata…)",
  "explorer.colSource": "Quelle",
  "explorer.colValue": "Wert",
  "explorer.empty": "Keine Datenpunkte für die aktuelle Abfrage gefunden.",

  // ── Data explorer: views ────────────────────────────────────────────────
  "explorer.tabChart": "Diagramm",
  "explorer.tabRaw": "Rohdatenpunkte",
  "explorer.tabOverview": "Metriken",

  // ── Data explorer: metric picker ────────────────────────────────────────
  "explorer.metrics": "Metriken:",
  "explorer.metricsNone": "Keine Metrik ausgewählt",
  "explorer.metricsSelected_one": "{count} Metrik",
  "explorer.metricsSelected_other": "{count} Metriken",
  "explorer.metricFilterPlaceholder": "Metriken filtern…",
  "explorer.clearSelection": "Auswahl leeren",
  "explorer.metricsEmpty": "Noch keine Metriken gespeichert.",
  "explorer.metricsNoMatch": "Keine Metrik passt zu diesem Filter.",

  // ── Data explorer: raw point log ────────────────────────────────────────
  "explorer.rawCount_one": "{count} Treffer",
  "explorer.rawCount_other": "{count} Treffer",
  "explorer.rawTruncated": "Angezeigt werden die neuesten {shown} von {total} Treffern.",
  "explorer.liveQuery": "Live-TimescaleDB-Abfrage",
  "explorer.sampleNote":
    "Diagramm und Tabelle lesen die neuesten {count} Datenpunkte. Öffne eine einzelne Metrik im Tab {tab}, um stattdessen deren eigene Historie zu laden.",
  "explorer.scopeActive": "Einzeln geladen: {metric}",
  "explorer.scopeClear": "Zurück zu allen Metriken",
  "explorer.colTimestamp": "Zeitstempel",
  "explorer.colMetric": "Metrik",
  "explorer.colMetadata": "Metadaten (JSON)",
  "explorer.colDetails": "Details",
  "explorer.inspect": "JSON inspizieren",
  "explorer.inspectorTitle": "Rohdatenpunkt",
  "explorer.inspectorMetadata": "Metadaten (JSONB)",

  // ── Data explorer: metric overview ──────────────────────────────────────
  "explorer.overviewHint":
    "Jeder Metriktyp dieses Workspace, gezählt über die gesamte Historie und nicht über die geladene Stichprobe. Öffne einen, um seine Rohdatenpunkte zu lesen.",
  "explorer.overviewEmpty":
    "Noch keine Metriken gespeichert, also gibt es nichts zusammenzufassen.",
  "explorer.overviewFailed": "Die Metrikübersicht konnte nicht geladen werden.",
  "explorer.colUnit": "Einheit",
  "explorer.colPoints": "Datenpunkte",
  "explorer.colTypical": "Aussagekräftiger Wert",
  "explorer.colRange": "Min / Max",
  "explorer.colLatest": "Neuester",
  "explorer.showRaw": "Rohdatenpunkte",
  "explorer.unregistered": "Nicht im Register",
  "explorer.aggAverage": "Durchschnitt",
  "explorer.aggSum": "Summe",
  "explorer.aggMax": "Maximum",
  "explorer.aggLast": "Letzter Wert",

  // ── Remaining OIDC and profile fields ───────────────────────────────────
  "oidc.emptyState":
    "Noch kein Anbieter konfiguriert. Die Anmeldung per E-Mail und Passwort funktioniert unabhängig davon.",
  "oidc.toggleSignup": "Registrierung erlauben",
  "oidc.toggleSignupHint": "Legt bei unbekannter Identität ein neues Konto an.",
  "oidc.toggleVerified": "Verifizierte E-Mail verlangen",
  "oidc.toggleVerifiedHint": "Empfohlen. Ohne Verifizierung ist die Adresse keine Identität.",
  "oidc.issuerHint":
    "Der Issuer wird beim Speichern geprüft: das Discovery-Dokument muss erreichbar sein und denselben Issuer nennen.",
  "profile.currentPassword": "Aktuelles Passwort",
  "profile.newPassword": "Neues Passwort",

  // ── Connector dialog ────────────────────────────────────────────────────
  "modal.catNutrition": "Ernährung & Tagebuch",
  "modal.desc.yazio":
    "Aktiv: Der Importer fragt Mahlzeiten, Kalorien und Nährwerte aus deinem Yazio-Tagebuch ab.",
  "modal.desc.whoop":
    "Aktiv: Der Importer fragt Recovery Score, HRV, Schlafphasen, Ruhepuls und Strain ab.",
  "modal.desc.apple_health":
    "Passiv: Health Auto Export sendet Schritte, Herzfrequenz, Schlafphasen und Workouts an deinen Webhook.",
  "modal.desc.streak":
    "Passiv: Streak 2.0 sendet Workouts, Sätze, Wiederholungen und Gewichte an deinen REST-Webhook.",
  "modal.desc.dawarich":
    "Aktiv: Der Importer fragt Standorte, GPS-Punkte und Bewegungsstrecken von deinem Dawarich-Server ab.",
  "modal.desc.home_assistant":
    "Aktiv: Liest Temperatur, Luftfeuchte, Licht und weitere freigegebene Sensorzustände.",
  "modal.desc.weather":
    "Aktiv: Importiert lokale Wetterzeitreihen über eine Open-Meteo-kompatible API.",
  "modal.desc.calendar": "Aktiv: Importiert freigegebene Termine und tägliche Belegungsdauer.",
  "modal.needEmailPassword": "Bitte gib sowohl E-Mail als auch Passwort ein.",
  "modal.needYazioToken": "Bitte gib einen Yazio Bearer Access Token ein.",
  "modal.needDawarichKey": "Bitte gib den Dawarich API Key ein.",
  "modal.needCalendarUrl": "Bitte gib die URL deines Kalender-Feeds (.ics) ein.",
  "modal.calendarUrlScheme": "Die Kalender-URL muss mit http:// oder https:// beginnen.",
  "modal.needBaseUrl": "Bitte gib die HTTPS-Basis-URL der Provider-API ein.",
  "modal.baseUrlLabel": "Basis-URL",
  "modal.calendarUrlLabel": "Kalender-Feed-URL",
  "modal.displayNameLabel": "Name",
  "modal.displayNamePlaceholder": "z. B. Privat",
  "modal.displayNameHint":
    "Erscheint auf der Connector-Karte. Denselben Anbieter kannst du mehrfach einrichten — der Name unterscheidet die Instanzen.",
  "modal.needDisplayName": "Bitte gib diesem Connector einen Namen.",
  "modal.credentialsStoredBody":
    "Du kannst Abfrage-Frequenz und Zeitraum anpassen, ohne die Zugangsdaten neu einzugeben.",
  "modal.tokenLabel": "Zugriffstoken",
  "modal.tokenPlaceholder": "Bearer Token / API Key",
  "modal.keepTokenPlaceholder": "•••••••• (Token beibehalten)",
  "modal.setupGuide": "Einrichtungsanleitung",
  "modal.weatherPlaceLabel": "Ort",
  "modal.weatherPlacePlaceholder": "Stadt oder Ortsname",
  "modal.weatherSearch": "Suchen",
  "modal.weatherSearching": "Suche läuft …",
  "modal.weatherNoPlaces": "Es wurde kein Ort mit diesem Namen gefunden.",
  "modal.weatherSearchFailed":
    "Der Ort konnte nicht nachgeschlagen werden. Gib die Koordinaten direkt ein.",
  "modal.weatherChosenPlace": "Verwendet wird {place}",
  "modal.weatherLatitude": "Breitengrad",
  "modal.weatherLongitude": "Längengrad",
  "modal.weatherNeedCoordinates":
    "Bitte wähle einen Ort aus oder gib Breiten- und Längengrad selbst ein.",
  "modal.weatherCoordinatesRange":
    "Der Breitengrad muss zwischen -90 und 90 liegen, der Längengrad zwischen -180 und 180.",
  "modal.weatherModeGuided": "Geführt",
  "modal.weatherModeCustom": "Eigene URL",
  "modal.weatherRequestUrlLabel": "Vollständige Abfrage-URL",
  "modal.weatherRequestUrlHint":
    "Wird exakt so gesendet, samt Query — eine aus der Anbieter-Dokumentation kopierte URL funktioniert also, einschließlich des Archiv-Endpunkts für Zeiträume, die die Forecast-API nicht mehr abdeckt. Der Importzeitraum wird nur ergänzt, wo du keinen gesetzt hast.",
  "modal.weatherNeedRequestUrl":
    "Bitte gib eine vollständige URL an, die mit http:// oder https:// beginnt.",
  "modal.weatherBaseUrl": "Anbieter-URL",
  "modal.weatherBaseUrlHint":
    "Open-Meteo ist voreingestellt und braucht keinen API Key. Ersetze die URL nur für einen selbst gehosteten oder kommerziellen Endpunkt.",
  "modal.needApiKey": "Bitte gib einen gültigen API Key für {provider} ein.",
  "modal.needApiKeyOrGenerate":
    "Bitte gib einen gültigen API Key für {provider} ein oder generiere einen.",
  "modal.saved": "{provider}-Einstellungen gespeichert.",
  "modal.saveFailed": "Konfiguration konnte nicht gespeichert werden.",
  "modal.networkError": "Netzwerkfehler: {message}",
  "modal.serverUnreachable": "Server nicht erreichbar",
  "modal.backToChoice": "Zurück zur Auswahl",
  "modal.pickSource": "Datenquelle auswählen",
  "modal.editProvider": "{provider} bearbeiten",
  "modal.connectProvider": "{provider} verbinden",
  "modal.guideFor": "Anleitung zu {provider} öffnen",
  "modal.pickHint":
    "Wähle einen Importer. Die Kennzeichnung zeigt, ob er einen Dienst selbst abfragt oder Daten von ihm empfängt:",
  "modal.available": "Verfügbar",
  "modal.activeShort": "Aktiv · fragt ab",
  "modal.passiveShort": "Passiv · empfängt",
  "modal.passiveTitle": "Passiver Importer · Daten werden zugestellt",
  "modal.activeTitle": "Aktiver Importer · fragt den Dienst selbst ab",
  "modal.passiveBody":
    "Du hinterlegst die Webhook-Adresse und den Header-Schlüssel. Der externe Dienst sendet neue Daten ereignisbasiert; ein Sync-Intervall ist nicht erforderlich.",
  "modal.activeBody":
    "Du hinterlegst Zugangsdaten. Der Importer ruft den externen Dienst nach dem konfigurierten Intervall und Zeitraum ab.",
  "modal.credentialsStored": "Zugangsdaten sind hinterlegt (Fernet AES-256)",
  "modal.keepCredentials": "Bestehende Zugangsdaten beibehalten…",
  "modal.keepUnchanged": "•••••••• (unverändert lassen)",
  "modal.keepCredentialsShort": "•••••••• (Zugangsdaten beibehalten)",
  "modal.pasteYazioToken": "Füge deinen Yazio Bearer Token hier ein",
  "modal.keepApiKey": "•••••••• (API Key beibehalten)",
  "modal.pasteDawarichKey": "Füge deinen Dawarich API Key hier ein",
  "modal.icsHint":
    "Öffentliche und private ICS-Feeds (Outlook, Google, Nextcloud) funktionieren, und keiner davon braucht einen API Key. Eine private Feed-Adresse ist selbst das Geheimnis: sie wird verschlüsselt gespeichert und nie protokolliert.",
  "modal.intervalSection": "Abfrage-Intervall & Zeitraum bearbeiten",
  "modal.everyHour": "Jede Stunde",
  "modal.everyNHours": "Alle {count} Stunden",
  "modal.everyNHoursDefault": "Alle {count} Stunden (Standard)",
  "modal.daily": "Täglich (24 Std)",
  "modal.weekly": "Wöchentlich (168 Std)",
  "modal.importPeriod": "Import-Zeitraum",
  "modal.lastNDays": "Letzte {count} Tage",
  "modal.lastNDaysDefault": "Letzte {count} Tage (Standard)",
  "modal.guide": "Anleitung",
  "modal.syncFrequency": "Sync-Frequenz",
  "modal.yazioTokenMode": "Bearer Token direkt eingeben",
  "modal.yazioTokenOptional": "Bearer Token (optional)",
  "modal.yazioLoginMode": "Yazio Login",
  "modal.yazioLoginOptional": "Yazio Login (optional)",
  "modal.modeConnect": "Jetzt verknüpfen",
  "modal.modeFile": "Einmaliger Import",
  "modal.modeConnectHint": "Der Connector holt deine Daten selbst, im unten eingestellten Takt.",
  "modal.modeFileHint":
    "Keine Kontoverknüpfung: Du lädst den Export hoch, den dieser Anbieter dir gibt, und er wird in diesen Connector eingelesen. Verknüpfen kannst du ihn später trotzdem — dieselben Daten bleiben eine Reihe.",
  "modal.fileFlowLead": "Wird per Datei befüllt:",
  "modal.fileFlowBody":
    "Es wird nichts abgefragt und keine Zugangsdaten gespeichert. Nach dem Speichern beim Connector „Hochladen“ öffnen und den Export auswählen.",
  "modal.passiveFlowLead": "Passiver Datenfluss:",
  "modal.passiveFlowBody":
    "Nach dem Speichern sendet die konfigurierte App Daten an die oben angezeigte URL. Neue Daten werden ohne manuelles Abfragen verarbeitet.",
  "modal.back": "Zurück",
  "modal.saving": "Speichere…",
  "modal.saveSettings": "Einstellungen speichern",
  "modal.saveConnection": "Verbindung speichern",

  // ── Connector categories ────────────────────────────────────────────────
  "modal.catRecovery": "Regeneration & Schlaf",
  "modal.catVitals": "Fitness & Vitaldaten",
  "modal.catStrength": "Krafttraining",
  "modal.catLocation": "Standort & GPS",
  "modal.catSmartHome": "Smart Home",
  "modal.catEnvironment": "Umwelt",
  "modal.catRoutine": "Routine & Stress",

  // ── Analysis ────────────────────────────────────────────────────────────
  "analysis.tabOverview": "Überblick",
  "analysis.tabCorrelations": "Zusammenhänge",
  "analysis.tabAnomalies": "Auffälligkeiten",
  "analysis.tabQuality": "Datenqualität",
  "analysis.loadFailed": "Analysen konnten nicht geladen werden.",
  "analysis.computing": "Analysen werden berechnet…",
  "analysis.title": "Zusammenhänge & Muster",
  "analysis.subtitleTail": "Zusammenhänge — keine Ursachen.",
  "analysis.window": "Zeitraum",
  "analysis.fromPercent": "ab {percent} %",
  "analysis.onlySignificant": "nur statistisch signifikante",
  "analysis.disclaimer":
    "Jedes Ergebnis beschreibt einen statistischen Zusammenhang, keine Ursache und Wirkung. Nichts davon ist eine medizinische Empfehlung.",
  "analysis.minStrength": "Mindeststärke",
  "analysis.all": "alle",
  "analysis.howToRead": "Wie diese Analysen zu lesen sind",
  "analysis.noData":
    "Es liegen noch keine Daten für Analysen vor. Richte einen Connector ein und importiere Daten für mindestens zwei Wochen.",
  "analysis.excludedForQuality": "{count} wegen zu dünner Datenlage ausgeblendet",
  "analysis.allMetricsQualify": "alle Metriken erfüllen die Mindestanforderungen",
  "analysis.significantRelationships": "Signifikante Zusammenhänge",
  "analysis.ofPairsChecked": "von {count} geprüften Paaren",
  "analysis.unusualDays": "Auffällige Tage",
  "analysis.outsideNormal": "außerhalb deines persönlichen Normalbereichs",
  "analysis.noneMatchFilters":
    "Keine Zusammenhänge, die die gewählten Filter erfüllen. Das ist ein gültiges Ergebnis — nicht jede Metrik hängt mit einer anderen zusammen.",
  "analysis.laggedTitle": "Zeitversetzte Zusammenhänge",
  "analysis.laggedTail": "später. Eine zeitliche Reihenfolge ist kein Beleg für eine Ursache.",
  "analysis.lagDays": "+{count} Tage",
  "analysis.sameDirection": "gleichläufig",
  "analysis.oppositeDirection": "gegenläufig",
  "analysis.tooFewForTrend": "Zu wenige Tage für eine Trendaussage.",
  "analysis.trendStats": "Mittelwert {mean} · R² {r2} · n={n} Tage",
  "analysis.tooFewForNormalRange":
    "Zu wenige Tage, um einen persönlichen Normalbereich zu bestimmen.",
  "analysis.anomalyBasis":
    "Grundlage: Median und mittlere absolute Abweichung über {days} Tage. Auffälligkeit bedeutet ungewöhnlich für dich, nicht",
  "analysis.tooFewForWeekly": "Mindestens zwei Wochen Daten nötig, um Wochenmuster zu erkennen.",
  "analysis.colDays": "Tage",
  "analysis.sufficient": "ausreichend",
  "analysis.tooThin": "zu dünn",
  "analysis.scaleStrongOpposite": "stark gegenläufig",
  "analysis.scaleNone": "kein Zusammenhang",
  "analysis.scaleStrongSame": "stark gleichläufig",
  "analysis.scaleLabel":
    "Farbskala von stark gegenläufig über kein Zusammenhang zu stark gleichläufig",
  "analysis.scaleEnds": "gegenläufig ← → gleichläufig",
  "analysis.matrixHint":
    "Jede Zelle zeigt die Stärke des Zusammenhangs in Prozent. Leere Zellen bedeuten",
  "analysis.strongestTitle": "Auffälligste Zusammenhänge",
  "analysis.provenanceTitle": "Datenbasis",
  "analysis.sources": "Datenquellen: {list}",
  "analysis.significant": "signifikant (α = 0,05)",
  "analysis.notSignificant": "nicht signifikant",
  "analysis.limitsTitle": "Einschränkungen",
  "analysis.limitsBody":
    "Ein Zusammenhang ist keine Ursache. Beide Werte können von einem dritten, nicht erfassten Faktor abhängen.",
  "analysis.sparklineLabel": "Gleitender 7-Tage-Mittelwert",
  "analysis.footerSources": "Quellen: {list} · Analyseversion",

  // ── Analysis tiles ──────────────────────────────────────────────────────
  "analysis.usableMetrics": "Auswertbare Metriken",

  // ── Analysis sections ───────────────────────────────────────────────────
  "analysis.tabTrends": "Trends",
  "analysis.tabRoutines": "Routinen",

  // ── KI-Chat ────────────────────────────────────────────────────────────────
  "chat.title": "KI-Chat",
  "chat.subtitle": "Stelle Fragen zu deinen persönlichen Messwerten und Mustern.",
  "chat.statusChecking": "Chat-Verfügbarkeit wird geprüft…",
  "chat.statusReady": "ChatGPT {plan}",
  "chat.newConversation": "Neuer Chat",
  "chat.unavailableTitle": "Codex ist nicht verfügbar",
  "chat.unavailableBody":
    "Installiere die Codex CLI beim Analysis Service oder aktiviere sie im Service-Image, um den Chat zu nutzen.",
  "chat.loginTitle": "ChatGPT-Abonnement verbinden",
  "chat.loginBody":
    "Melde dich über den offiziellen Codex-Gerätefluss an. Die Plattform erhält oder speichert weder dein ChatGPT-Passwort noch dein Token.",
  "chat.loginAction": "ChatGPT verbinden",
  "chat.deviceInstruction": "Öffne die Anmeldeseite und gib diesen einmaligen Code ein.",
  "chat.deviceCodeLabel": "Einmaliger Code",
  "chat.copyCode": "Einmaligen Code kopieren",
  "chat.openLogin": "ChatGPT-Anmeldung öffnen",
  "chat.waitingForLogin": "Diese Seite macht nach der Anmeldung automatisch weiter.",
  "chat.welcomeTitle": "Was möchtest du verstehen?",
  "chat.welcomeBody":
    "Frage nach Trends, Datenqualität, ungewöhnlichen Werten oder Zusammenhängen zwischen deinen Messwerten. Daten werden ausschließlich über mandantengebundene Lese-Werkzeuge abgerufen.",
  "chat.userMessage": "Deine Nachricht",
  "chat.assistantMessage": "Nachricht des KI-Assistenten",
  "chat.inputPlaceholder": "Frage etwas zu deinen Daten…",
  "chat.inputLabel": "Nachricht an den KI-Assistenten",
  "chat.send": "Nachricht senden",
  "chat.sending": "Nachricht wird gesendet",
  "chat.disclaimer":
    "KI-Ausgaben können falsch sein. Zusammenhänge sind keine Ursachen und gesundheitliche Einordnungen sind keine medizinische Beratung.",
  "chat.errorStatus": "Die Chat-Verfügbarkeit konnte nicht geprüft werden.",
  "chat.errorLogin": "Die ChatGPT-Anmeldung konnte nicht gestartet werden.",
  "chat.errorCopy": "Der Code konnte nicht kopiert werden.",
  "chat.errorLoginRequired": "Verbinde dein ChatGPT-Abonnement, bevor du eine Nachricht sendest.",
  "chat.errorResponse": "Der Assistent konnte diese Antwort nicht abschließen.",
  "chat.errorStream": "Die Chat-Verbindung wurde unterbrochen.",
  // --- Ende des Katalogs ---
};
