/**
 * English messages — and the shape every other catalogue has to match.
 *
 * Keys are flat and read `area.thing`, because a flat object gives `keyof` a union
 * of every key for free: a typo in `t("sidebar.dahsboard")` is a compile error, and
 * so is a key this file has and `catalog-de.ts` does not.
 *
 * `{name}` placeholders are substituted by `translate()` in `provider.tsx`. Counts
 * that change the wording get two keys, `*_one` and `*_other`, chosen at the call
 * site — enough for German and English, and honest about not being a plural engine.
 *
 * Order follows the interface: shared words first, then the shell, then one section
 * per screen.
 */

export const en = {
  // ── Shared ─────────────────────────────────────────────────────────────────
  "common.cancel": "Cancel",
  "common.save": "Save",
  "common.saving": "Saving…",
  "common.close": "Close",
  "common.delete": "Delete",
  "common.pleaseWait": "Please wait…",
  "common.pending": "Pending",
  "common.unknown": "Unknown",
  "common.days_one": "{count} day",
  "common.days_other": "{count} days",
  "common.years_one": "{count} year",
  "common.years_other": "{count} years",

  // ── When a screen throws ────────────────────────────────────────────────────
  "crash.title": "This screen stopped working",
  "crash.detail":
    "Something in this view failed while rendering. Your data is unaffected — nothing was written, and the rest of the app still works.",
  "crash.retry": "Try this screen again",
  "crash.reload": "Reload the page",
  "crash.home": "Back to the overview",
  "crash.technical": "Technical detail",
  "crash.technicalHint":
    "Include this when reporting the problem. It names the code that failed, not your data.",
  "crash.digest": "Reference",
  "crash.fatalTitle": "The app could not start",
  "crash.fatalDetail":
    "The page failed before it could load anything, so this message is not translated.",

  // ── Language switcher ──────────────────────────────────────────────────────
  "lang.label": "Language",
  "lang.switchTo": "Switch to {language}",

  // ── Sidebar ────────────────────────────────────────────────────────────────
  "nav.primary": "Main navigation",
  "nav.more": "More",
  "sidebar.menu": "Menu",
  "sidebar.general": "General",
  "sidebar.overview": "Dashboard",
  "sidebar.explorer": "Data explorer",
  "sidebar.quality": "Data quality",
  "sidebar.analysis": "Analysis",
  "sidebar.chat": "AI chat",
  "sidebar.workouts": "Workouts",
  "sidebar.connectors": "Connectors",
  "sidebar.docs": "Documentation",
  "sidebar.docsTitle": "Open the platform documentation",
  "sidebar.settings": "Settings",
  "sidebar.logout": "Sign out",

  // ── Top header ─────────────────────────────────────────────────────────────
  "header.docs": "Documentation",
  "header.refresh": "Refresh",
  "header.refreshTitle": "Reload the whole page",
  "header.addConnector": "Add connector",

  // ── Theme ─────────────────────────────────────────────────────────────────
  "theme.label": "Colour theme",
  "theme.system": "System",
  "theme.light": "Light",
  "theme.dark": "Dark",

  // ── Legal footer and legal pages ───────────────────────────────────────────
  "footer.nav": "Legal and documentation",
  "footer.imprint": "Legal notice",
  "footer.privacy": "Privacy policy",
  "footer.docs": "Documentation",
  "footer.source": "Source code",
  "footer.sourceVersion": "Source code (v{version})",
  "footer.sourceCommit": "Source code ({commit})",
  "legal.nav": "Legal",
  "legal.backToApp": "Back to the application",
  "legal.imprintMeta": "Legal notice — Quantified Self",
  "legal.imprintMetaDescription":
    "Provider identification pursuant to § 5 DDG and § 18 (2) MStV.",
  "legal.privacyMeta": "Privacy policy — Quantified Self",
  "legal.privacyMetaDescription":
    "How the Quantified Self platform processes personal data, and on what legal basis.",
  "legal.notPublished":
    "The operator of this deployment has not published this document yet.",
  "legal.translationNote":
    "This is a courtesy translation. The German version is the legally binding one.",
  "legal.germanOnlyNote":
    "This document has been published in German only. The German version is the legally binding one.",

  // ── Sign in / sign up ──────────────────────────────────────────────────────
  "auth.tagline": "Your personal health and analytics platform.",
  "auth.welcomeBack": "Welcome back",
  "auth.createAccount": "Create account",
  "auth.name": "Name",
  "auth.email": "Email",
  "auth.password": "Password",
  "auth.signIn": "Sign in",
  "auth.signUp": "Create account",
  "auth.noAccount": "No account yet?",
  "auth.haveAccount": "Already registered?",
  "auth.toSignUp": "Sign up now",
  "auth.toSignIn": "Sign in here",
  "auth.registrationClosed": "Sign-up has been disabled by the administrator.",
  "auth.or": "or",
  "auth.redirecting": "Redirecting…",
  "auth.signInWith": "Sign in with {provider}",
  "auth.providerUnavailable": "Signing in through this provider is not possible.",
  "auth.failed": "Authentication failed",
  "auth.useExistingAccount": "Sign in with this email address instead.",
  "auth.callbackWorking": "Completing sign-in…",
  "auth.callbackFailed": "Sign-in could not be completed.",
  "auth.callbackRetry": "Back to sign-in",

  // ── Sign-in callback ────────────────────────────────────────────────────
  "auth.callbackTitle": "Sign-in failed",
  "auth.callbackDone": "Signed in. Redirecting…",
  "auth.callbackIncomplete": "The provider's response was incomplete.",
  "auth.callbackProviderCancelled": "Sign-in was cancelled by the provider.",

  // ── System warnings ─────────────────────────────────────────────────────
  "warnings.region": "System warnings",
  "warnings.severity.critical": "Critical",
  "warnings.severity.warning": "Warning",
  "warnings.severity.info": "Note",
  "warnings.openDocs": "Open the documentation",
  "warnings.dismiss": "Hide for a day",
  "warnings.dismissTitle": "Hide for a day — back tomorrow until it is fixed",
  "warning.password_published.title": "This password is publicly known",
  "warning.password_published.detail":
    "The hash of this password appeared in a published source — it was the development account earlier versions of this project shipped. bcrypt delays an attack, it does not prevent one: whoever holds the hash can try passwords offline for as long as they like.",
  "warning.password_published.action": "Change the password now — and anywhere else it is used.",
  // A connector that stopped importing. Reported because it once stopped for a day
  // in silence: every card still showed its last successful run, which is also what
  // a healthy connector looks like.
  "warning.connectors_overdue.title": "Scheduled imports are not running",
  "warning.connectors_overdue.detail":
    "{count} connector(s) are past their poll interval. The longest, {connector}, last imported {hours} hours ago.",
  "warning.connectors_overdue.action":
    "Check Core's scheduler log. A connection left idle in transaction holds the scheduler's advisory lock and stops every scheduled import.",
  "warning.insecure_jwt_secret.title": "JWT_SECRET is a published default",
  "warning.insecure_jwt_secret.detail":
    "Sessions are signed with a key that is printed in this project's own source. Anyone who knows it can issue a token for any account and any workspace.",
  "warning.insecure_jwt_secret.action": "Set a value of your own: {generate}",
  "warning.insecure_encryption_key.title": "ENCRYPTION_KEY is a published default",
  "warning.insecure_encryption_key.detail":
    "Every stored connector credential can be decrypted by anyone who knows this key — and it is in the source.",
  "warning.insecure_encryption_key.action":
    "Re-encrypt first, then switch: python -m core.rotate_encryption_key --old … --new … Changing it without that step makes every stored token permanently unreadable.",
  "warning.insecure_internal_secret.title": "INTERNAL_SERVICE_SECRET is a published default",
  "warning.insecure_internal_secret.detail":
    "With it, anyone can present themselves as an internal service and fetch decrypted connector credentials.",
  "warning.insecure_internal_secret.action": "Set a value of your own: {generate}",
  "warning.registration_open.title": "Self-service sign-up is open",
  "warning.registration_open.detail":
    "Anyone who knows this address can create an account and a workspace of their own.",
  "warning.registration_open.action":
    "Set ALLOW_REGISTRATION=false. The first account is created with python -m core.create_owner.",
  "warning.cookies_not_secure.title": "Session cookies without the Secure flag",
  "warning.cookies_not_secure.detail":
    "The cookies are sent over unencrypted connections too, where anyone on the path can read them.",
  "warning.cookies_not_secure.action":
    "Set COOKIE_SECURE=true. Harmless for local development: browsers treat localhost and 127.0.0.1 as trustworthy and accept Secure cookies there.",
  "warning.development_environment.title": "ENVIRONMENT is “{environment}”",
  "warning.development_environment.detail":
    "That is why the services start despite the points above. With a production-like ENVIRONMENT, Core and the Gateway refuse to start while any value is a published default.",
  "warning.development_environment.action": "Set ENVIRONMENT=production for a real deployment.",
  "warning.ingestion_stream_retention_mismatch.title":
    "The ingestion stream uses the wrong retention policy",
  "warning.ingestion_stream_retention_mismatch.detail":
    "The stream currently uses {actual_retention}; it must use {expected_retention}. An owner can reset it after confirming that the queue is empty.",
  "warning.ingestion_stream_retention_mismatch.action":
    "An owner can reset the ingestion stream from the dashboard after confirming the queue is empty.",
  "warning.ingestion_stream_retention_mismatch.confirm":
    "Reset the ingestion stream now? Core will proceed only when both pending counters are zero, and importer publishing will pause briefly during the reset.",
  "warning.ingestion_stream_retention_mismatch.controlDetail":
    "This control is available only to the workspace owner. Core checks both consumer counters, pauses normal importer subjects, then recreates the stream and subscription.",
  "warning.ingestion_stream_retention_mismatch.reset": "Reset ingestion stream",
  "warning.ingestion_stream_retention_mismatch.resetBusy": "Resetting ingestion stream…",
  "warning.ingestion_stream_retention_mismatch.resetDone": "Stream reset complete",
  "warning.ingestion_stream_retention_mismatch.resetSuccess":
    "The stream was recreated and the consumer subscription is ready.",
  "warning.ingestion_stream_retention_mismatch.resetPendingTitle":
    "Reset refused: events are still pending",
  "warning.ingestion_stream_retention_mismatch.resetPendingDetail":
    "Nothing was deleted. Pending events: {pending}; awaiting acknowledgement: {ackPending}.",
  "warning.ingestion_stream_retention_mismatch.countUnavailable": "unavailable",
  "warning.ingestion_stream_retention_mismatch.resetFailedTitle": "Reset could not be completed",
  "warning.ingestion_stream_retention_mismatch.resetFailedDetail":
    "Nothing was deleted. Review the operator fallback in the documentation before trying again.",

  // ── Daily story ────────────────────────────────────────────────────────────
  "day.eyebrow": "Your day",
  "day.title": "What happened",
  "day.subtitle":
    "Yesterday is a finished day. Today is shown as far as your connectors have reported it.",
  "day.loadFailed": "Your day could not be loaded. The data is unaffected.",
  "day.retry": "Try again",
  "day.yesterday": "Yesterday",
  "day.today": "Today",
  "day.stillArriving": "Still arriving",
  "day.nothingRecorded": "Nothing was recorded for this day.",
  "day.timeline": "During the day",
  "day.timelineTruncated": "Only the first entries of this day are shown.",
  "day.logged": "Logged that day",
  "day.loggedNote":
    "Grouped by meal rather than placed on the timeline: these are recorded for a day, not at an hour. A time is shown where the app that recorded it stated one.",
  "day.loggedSummed": "Added up from the individual entries, not stated by the provider.",
  "day.loggedTruncated": "Only the first entries of this day are shown.",
  "day.mealBreakfast": "Breakfast",
  "day.mealLunch": "Lunch",
  "day.mealDinner": "Dinner",
  "day.mealSnack": "Snack",
  "day.mealOther": "Other",
  "day.lastImport": "This connector last imported {timestamp}",
  "day.neverImported": "This connector has never completed an import",
  "day.vsPreviousDay": "vs. the day before",
  "day.expandAll": "Expand all",
  "day.collapseAll": "Collapse all",
  "day.mapSection": "Where the day happened",
  "day.valueCount_one": "{count} value",
  "day.valueCount_other": "{count} values",
  "day.eventCount_one": "{count} event",
  "day.eventCount_other": "{count} events",
  "day.mealCount_one": "{count} meal",
  "day.mealCount_other": "{count} meals",
  "day.multiSourceNote":
    "Where more than one connector reported a value, the source in brackets is the one shown. The two are never added together.",
  "day.laneSleep": "Sleep",
  "day.laneActivity": "Activity",
  "day.laneWorkout": "Workouts",
  "day.laneStrength": "Strength",
  "day.laneHeart": "Heart",
  "day.laneNutrition": "Nutrition",
  "day.laneBody": "Body",
  "day.laneLocation": "Places",
  "day.laneCalendar": "Calendar",
  "day.laneEnvironment": "Weather",
  "day.laneHome": "Home",
  "day.laneDeveloper": "Code",
  "day.laneCustom": "Your own metrics",
  "day.laneOther": "Other",

  // ── Overview ────────────────────────────────────────────────────────────
  "overview.title": "Dashboard",
  "overview.subtitle": "Aggregated analysis of the sensors and trackers you have connected.",
  "overview.empty": "No data points stored yet.",
  "overview.emptyAction": "Connect a source and import data",
  "overview.loadingChart": "Loading the chart…",
  "overview.loadingMap": "Loading the map…",
  "header.welcome": "Welcome back, {name}",

  // ── Data quality ────────────────────────────────────────────────────────
  "quality.eyebrow": "Data quality centre",
  "quality.title": "Data quality",
  "quality.subtitle":
    "Find gaps, conflicting sources and the next concrete step towards analyses you can rely on.",
  "quality.window": "Time window",
  "quality.windowDays": "{count} days",
  "quality.gapsTitle": "Data gaps",
  "quality.gapsDetail": "{metrics} metrics in the {days}-day window",
  "quality.conflictsTitle": "Conflicting sources",
  "quality.conflictsDetail": "Deviations above 5 %",
  "quality.conflictsNone": "No competing sources worth a second look.",
  "quality.conflictsHelp": "Check the units and which source should be the primary one.",
  "quality.perConnectorMoved":
    "Quarantined metrics, unstored provider fields and newly supported fields are shown on each connector's own page, because every one of them is a decision about that connector. Open a connector under Connectors to review them.",
  "quality.conflictsListTitle": "Which measurements disagree",
  "quality.conflictsListHint":
    "The same metric on the same day, reported differently by two connectors. Both readings are kept; choosing a primary source per metric decides which one is used.",
  "quality.conflictsMore": "{count} further disagreements not shown",
  "quality.recommendationComplete": "The data looks complete.",
  "quality.recommendationMinor": "Small gaps: usable for analysis, but check the trends.",
  "quality.recommendationSerious":
    "Check the connector, its token and how often it syncs before drawing conclusions.",
  "quality.explainTitle": "What do these numbers mean?",
  "quality.explainBody":
    "Gaps weaken every trend and correlation drawn from the data. A source conflict means two integrations report different values for the same period. Stabilise the data first, interpret correlations second.",
  "quality.explainDocs": "Documentation on data quality",
  "quality.interruptionsTitle": "Interruptions",
  "quality.interruptionsHint":
    "Metrics recorded continuously — heart rate, weather — measured against the rate they actually kept rather than against calendar days.",
  "quality.unsupportedTitle": "Not yet supported",
  "quality.newlySupportedTitle": "Now supported ({count})",
  "quality.newlySupportedHint":
    "These fields used to arrive without being stored, and are being stored now. Support is re-checked on every import, so this list fills itself in — and where the earlier data can still be fetched from the provider, it is fetched automatically.",
  "quality.colConnector": "Connector",
  "quality.colField": "Field",
  "quality.colMetric": "Metric",
  "quality.colSince": "Since",
  "quality.colHistory": "Earlier data",
  "quality.historyQueued": "Being fetched automatically",
  "quality.historyRecovered": "Fetched again on {date}",
  "quality.historyOnDevice": "Only on the device that sent it",
  "quality.unsupportedHint":
    "Your device sends these fields and this platform does not store them yet. Only the field names and their types are recorded here — never a value.",
  "quality.unsupportedSummary": "Unsupported fields ({count})",
  "quality.unsupportedLifecycle":
    "This report is shape-only. A field leaves this list after an import stores it; historical observations remain for audit, and nothing is deleted automatically.",
  "quality.unsupportedConnector": "Connector",
  "quality.unsupportedField": "Field",
  "quality.unsupportedKind": "Type",
  "quality.unsupportedSeen": "Seen",
  "quality.unsupportedLastSeen": "Last seen",
  "quality.unsupportedCopy": "Copy report",
  "quality.unsupportedCopied": "Copied",
  "quality.quarantineTitle": "Held for your decision",
  "quality.quarantineHint":
    "These values are safe outside charts and analysis until you map, adopt, discard or keep their connector-specific name.",
  "quality.quarantineCapacityTitle": "Quarantine capacity",
  "quality.quarantineCapacityIntro":
    "Unknown values are held here for mapping. Resolve them before the connector reaches its limit; values arriving after a full limit cannot be recovered by mapping later.",
  "quality.quarantineCapacityPending":
    "Unknown values are waiting for a decision. Resolve them before the next large import so the quarantine has room for new values.",
  "quality.quarantineCapacityHalf":
    "The quarantine is {percent}% full. If the limit is reached, additional unknown values will not be retained and cannot be mapped later.",
  "quality.quarantineCapacityNearFull":
    "The quarantine is {percent}% full. Resolve this connector now: additional unknown values may soon be refused and lost for later mapping.",
  "quality.quarantineCapacityFull":
    "The quarantine limit is full. Additional unknown values are not retained and cannot be recovered by mapping this connector later.",
  "quality.quarantineCapacityRefused":
    "Unknown values have already been refused for this connector. They are not in quarantine; re-import the source after resolving the mapping.",
  "quality.quarantineCapacityUsage":
    "Held points: {rows} / {maxRows} · Unknown names: {names} / {maxNames}",
  "quality.quarantineConnectorDetail": "{connector} · {count} point(s)",
  "quality.mappingDecision": "Mapping decision",
  "quality.mappingMap": "Map to a registry metric",
  "quality.mappingAdopt": "Adopt as a custom metric",
  "quality.mappingDiscard": "Discard and keep discarding",
  "quality.mappingKeep": "Keep unresolved",
  "quality.mappingTarget": "Target metric",
  "quality.mappingCustomName": "custom_metric_name",
  "quality.mappingSourceUnit": "Source unit",
  "quality.mappingTargetUnit": "Declared unit",
  "quality.mappingAggregation": "Aggregation",
  "quality.mappingCadence": "Cadence",
  "quality.mappingAverage": "Average",
  "quality.mappingSum": "Sum",
  "quality.mappingLast": "Last",
  "quality.mappingMax": "Maximum",
  "quality.mappingDaily": "Daily",
  "quality.mappingContinuous": "Continuous",
  "quality.mappingEvent": "Event",
  "quality.mappingApply": "Apply and replay",
  "quality.mappingSaving": "Applying…",
  "quality.mappingKeepIndefinitely": "Keep unresolved values indefinitely",
  "quality.largestGaps": "Largest data gaps",
  "quality.largestGapsHint":
    "Consecutive missing days. “Backfill” opens the import dialog with exactly this period filled in.",
  "quality.noGaps": "No data gaps found in the {days}-day window.",
  "quality.moreRanges": "… and {count} more ranges",
  "quality.backfillTitle": "Backfill missing data",
  "quality.backfillSource": "Backfill {source}",
  "quality.backfillHint":
    "The import dialog proposes the period that is missing and skips what is already stored.",

  // ── Charts and map ──────────────────────────────────────────────────────
  "chart.calories": "Calories (kcal)",
  "chart.protein": "Protein (g)",
  "chart.carbs": "Carbohydrates (g)",
  "chart.fat": "Fat (g)",
  "chart.sleepScore": "Sleep score",
  "chart.readinessScore": "Readiness score",
  "chart.categoryNutrition": "Nutrition",
  "chart.categoryBio": "Sleep & bio scores",
  "chart.period": "Period:",
  "chart.presetAll": "All",
  "chart.presetCustom": "Dates…",
  "chart.rangeTo": "to",
  "chart.typeArea": "Area chart",
  "chart.typeLine": "Line chart",
  "chart.typeBar": "Bar chart",
  "chart.refresh": "Refresh the chart",
  "chart.emptyPeriod": "No data points in the selected period.",
  // Chart.js draws into a `<canvas role="img">`, and a role of img with no
  // accessible name is a chart a screen reader announces as nothing at all. The
  // series names are the only useful description available here.
  "chart.aria": "Chart of {metrics}",
  "chart.emptyFilter": "No data points for the current filter.",
  "map.routeAria": "Map of the recorded route",
  "map.tilesFailed": "The map could not be loaded. Falling back to the plain view.",
  "map.loading": "Loading GPS data…",
  "map.today": "Today",
  "map.showTiles": "Load the map",
  "map.hideTiles": "Hide the map",
  "map.showTilesTitle": "Loads map tiles from an external provider",
  "map.hideTilesTitle": "Back to the plain view",
  "map.privacyLead":
    "No location data is sent to a map provider. Loading the tiles makes the part of the map you are looking at visible to that provider.",
  "map.empty": "No GPS points in the selected period.",
  "map.pointCount": "{count} points",
  "map.simplifiedTo": "simplified to {count}",
  "map.vectorMode": "Vector view",

  // ── Map privacy detail ──────────────────────────────────────────────────
  "map.privacyDetail":
    "No location data is sent to a map provider. When the map loads, your browser requests tiles from the provider directly, which makes the part of the map you are looking at visible to them.",
  "map.headline": "GPS locations & route",

  // ── Metric cards ────────────────────────────────────────────────────────
  "cards.range": "Range: {min} – {max} {unit}",

  // ── Connectors ──────────────────────────────────────────────────────────
  "connectors.title": "Connectors",
  "connectors.subtitle":
    "Manage your data sources and their credentials, and watch the event broker live.",
  "connectors.desc.yazio":
    "Calories, macronutrients (protein, carbohydrates, fat) and the meal diary.",
  "connectors.desc.dawarich":
    "GPS locations and movement traces, stored with a PostGIS spatial index.",
  "connectors.desc.whoop": "Heart-rate variability, sleep stages and the strain score.",
  "connectors.desc.apple_health":
    "Steps, active energy, resting heart rate and sleep stages via Health Auto Export.",
  "connectors.desc.streak": "Strength training from Streak 2.0: exercises, sets, reps and weight.",
  "connectors.desc.home_assistant": "Temperature, humidity, light and sound sensors.",
  "connectors.desc.weather": "Temperature, air pressure, precipitation and the UV index.",
  "connectors.desc.calendar": "ICS feeds: appointments, meeting duration and busy hours per day.",
  "connectors.desc.github": "Commits, changed lines, pull requests and reviews per day, and per repository.",
  "connectors.nameWeather": "Weather",
  "connectors.nameCalendar": "Calendar",
  "connectors.confirmDelete":
    "Really remove the {source} connection and the credentials stored with it?",
  "connectors.passive": "Passive connector",
  "connectors.active": "Active connector",
  "connectors.passiveHint": "Passive · receives data",
  "connectors.activeHint": "Active · polls the service",
  "connectors.soon": "Coming soon",
  "connectors.openDocs": "Open the documentation",
  // Names the state, not a cause. The row shows `last_sync_message` underneath, and
  // that is the only thing here that knows why a run failed — a badge that claimed
  // "HTTP 401 auth error" labelled an unreadable export archive as an expired token.
  "connectors.syncFailed": "Last run failed",
  "connectors.disconnect": "Disconnect and delete this connector",
  "connectors.connectNow": "Connect now",
  "connectors.loadingDetails": "Loading connectors and queue details…",
  "connectors.colSource": "Connection / source",
  "connectors.colTransfer": "Data transfer",
  "connectors.everyHours": "Every {hours} h ({lookback} h lookback)",
  "connectors.edit": "Edit",
  "connectors.emptyList": "No connectors configured yet.",
  "connectors.addFirst": "Add the first connector",

  // ── Connector state ─────────────────────────────────────────────────────
  "connectors.ready": "Ready",

  // ── Connector actions ───────────────────────────────────────────────────
  "connectors.import": "Import",
  "connectors.upload": "Upload",
  "connectors.fileDriven": "Fed by uploaded exports",
  "connectors.queued": "Queued",
  "connectors.newConnector": "New connector",
  "connectors.docs": "Docs",
  "connectors.processing": "Event queued (processing)",
  "connectors.loadingCore": "Core is loading",
  "connectors.readyActive": "Ready / active",
  "connectors.webhookDriven": "Webhook · event-driven",
  "connectors.tableTitle": "Configured connections & live queue status",
  "connectors.autoRefresh": "Auto-refresh {seconds}s",
  "connectors.configuredCount_one": "{count} connector configured",
  "connectors.configuredCount_other": "{count} connectors configured",
  "connectors.colQueue": "NATS queue & status",
  "connectors.colLastSync": "Last sync",
  "connectors.colActions": "Actions",
  "connectors.addAnother": "Add another",
  "connectors.instanceCount_one": "{count} configured",
  "connectors.instanceCount_other": "{count} configured",
  "connectors.tabs": "Connector views",
  "connectors.tabCurrent": "Current importers",
  "connectors.tabAvailable": "Add importer",
  "connectors.availableHint": "Choose a data source to configure for this workspace.",
  "connectors.showRuns": "Import runs",
  "connectors.runsActiveHint": "{count} import running right now",
  "connectors.details": "Runs",
  "connectors.openDetails": "Open importer run details",

  // ── Importer detail page ───────────────────────────────────────────────
  "importerDetail.eyebrow": "Importer details",
  "importerDetail.back": "Back to connectors",
  "importerDetail.backToConnectors": "Back to connectors",
  "importerDetail.notFound": "Connector not found",
  "importerDetail.notFoundHint": "This connector is not configured in the current workspace.",
  "importerDetail.totalRuns": "Total runs",
  "importerDetail.successfulRuns": "Successful",
  "importerDetail.failedRuns": "Failed",
  "importerDetail.activeRuns": "Active",
  "importerDetail.typicalDuration": "Typical duration",
  "importerDetail.latestRun": "Latest run",
  "importerDetail.status": "Status",
  "importerDetail.trigger": "Trigger",
  "importerDetail.started": "Started",
  "importerDetail.finished": "Finished",
  "importerDetail.duration": "Duration",
  "importerDetail.mode": "Mode",
  "importerDetail.modeSmart": "Smart",
  "importerDetail.modeForce": "Force",
  "importerDetail.modeOther": "Other",
  "importerDetail.requestId": "Request ID",
  "importerDetail.operatorDiagnostics": "Operator diagnostics",
  "importerDetail.operatorPhase": "Phase",
  "importerDetail.operatorProgress": "Progress",
  "importerDetail.operatorProgressUnknown": "Unknown",
  "importerDetail.operatorProgressValue": "{processed} of {total} events ({percent}%)",
  "importerDetail.operatorElapsed": "Elapsed",
  "importerDetail.operatorMessage": "Sanitized operator message",
  "importerDetail.redacted": "[redacted]",
  "importerDetail.operatorStalled":
    "This run is taking unusually long. Check importer, Core and broker health; the request ID links the logs.",
  "importerDetail.operatorActiveGuidance":
    "This run is still active. Check the request ID in service logs before retrying.",
  "importerDetail.historyTitle": "Complete run history",
  "importerDetail.autoRefresh": "Refreshes every {seconds}s",
  "importerDetail.loading": "Loading run history…",
  "importerDetail.loadingMore": "Loading more…",
  "importerDetail.loadMore": "Load older runs",
  "importerDetail.historyFailed": "The run history could not be loaded.",
  "importerDetail.noRuns": "No import runs have been recorded yet.",
  "importerDetail.noDuration": "Not finished",
  "importerDetail.durationSeconds": "{count} s",
  "importerDetail.durationMinutes": "{count} min",
  "importerDetail.points":
    "{processed} processed · {accepted} accepted · {duplicate} duplicates · {rejected} rejected · {unsupported} unsupported fields · {expected} expected",
  "importerDetail.providerWindow": "Provider coverage: {start} – {end}",
  "importerDetail.backlog": "Broker backlog at finish: {count}",
  "importerDetail.unknown": "unknown",
  "importerDetail.statusSuccess": "Success",
  "importerDetail.statusError": "Failed",
  "importerDetail.statusSkipped": "Skipped",
  "importerDetail.statusQueued": "Queued",
  "importerDetail.statusRunning": "Running",
  "importerDetail.statusLoading": "Loading in Core",
  "importerDetail.statusUnknown": "Unknown",
  "importerDetail.triggerScheduled": "Scheduled",
  "importerDetail.triggerManual": "Manual",
  "importerDetail.triggerPush": "Push",
  "importerDetail.triggerUpload": "Upload",
  "importerDetail.triggerOther": "Other",
  "importerDetail.messageQueued": "The importer has been queued.",
  "importerDetail.messageLoading": "Core is loading the published data.",
  "importerDetail.messageCoreLoaded": "Core loaded all published data.",
  "importerDetail.messageCredentialsMissing": "No active connector credentials were configured.",
  "importerDetail.messageSkipped": "This import was skipped.",
  "importerDetail.messageInFlight": "Another import for this connector is already running.",
  "importerDetail.messageFailed": "The import could not be completed.",
  "importerDetail.messageImporterFailed": "The importer reported an error.",
  "importerDetail.messageUploadRead": "The export was read successfully.",
  "importerDetail.messageUploadPublishing": "The export is being sent to Core.",
  "importerDetail.messageUploadFailed": "The export could not be processed.",
  "importerDetail.messageCoreDeliveryFailed":
    "Core stopped retrying an event; this import is incomplete and should be retried.",
  "importerDetail.messageInvalidJson": "The provider sent invalid JSON.",
  "importerDetail.messagePayloadInvalid": "The provider payload schema was not recognized.",
  "importerDetail.messageBrokerFailed":
    "The event broker did not accept the import; retry it when the broker is healthy.",

  // ── API keys and external sign-in ───────────────────────────────────────
  "apikeys.loadFailed": "The keys could not be loaded.",
  "apikeys.createFailed": "The key could not be created.",
  "apikeys.confirmRevoke":
    "Really revoke key {prefix}…? Devices using it stop being able to send data immediately.",
  "apikeys.copyFailed": "Copying did not work — please select it by hand.",
  "apikeys.headerHint":
    "A separate X-Tenant-ID header is not needed: the tenant is derived from the key itself. Older apps may keep sending X-Api-Key.",
  "apikeys.docs": "Documentation on API keys",
  "apikeys.shownOnce": "This key is shown only once",
  "apikeys.copy": "Copy to the clipboard",
  "apikeys.storeNow":
    "Store it in the app now. Once this closes it cannot be shown again — only revoked and replaced.",
  "apikeys.none": "No key for {provider} yet. Create one to start receiving data.",
  "apikeys.created": "Created {date}",
  "apikeys.expires": "expires {date}",
  "apikeys.lastUsed": "last used {date}",
  "apikeys.neverUsed": "never used",
  "apikeys.statusActive": "active",
  "apikeys.statusRevoked": "revoked",
  "apikeys.rotateTitle": "Create a successor; this key stays valid until it is revoked",
  "apikeys.revokeTitle": "Invalidate immediately",
  "apikeys.namePlaceholder": "e.g. iPhone",
  "apikeys.noExpiry": "No expiry",
  "apikeys.rotationFailed": "Rotation failed.",
  "apikeys.revokeFailed": "Revocation failed.",
  "apikeys.webhookTitle": "{provider} webhook configuration",
  "apikeys.headerExample": "Authorization: Bearer <your-key>",
  "apikeys.hideRevealed": "Got it, hide",
  "apikeys.title": "API keys ({count} active)",
  "apikeys.expiryLabel": "Expiry",
  "apikeys.create": "Create key",
  "apikeys.rotationHint":
    "Several active keys are intended: that is how you rotate without interrupting the data flow. Revoke the old one once the",
  "oidc.forbidden":
    "Only owners and administrators of the deployment's platform workspace can manage login providers.",
  "legalAdmin.title": "Legal texts",
  "legalAdmin.lead":
    "Write your own imprint and privacy policy. Until you do, both pages state that the document has not been published.",
  "legalAdmin.forbidden":
    "Only owners and administrators of the deployment's platform workspace can edit the legal texts.",
  "legalAdmin.loadFailed": "The legal texts could not be loaded.",
  "legalAdmin.saveFailed": "The document could not be saved.",
  "legalAdmin.stateCustom": "Your own text is published.",
  "legalAdmin.stateDefault": "Nothing is published yet.",
  "legalAdmin.edit": "Edit",
  "legalAdmin.german": "German",
  "legalAdmin.english": "English",
  "legalAdmin.preview": "Preview",
  "legalAdmin.write": "Write",
  "legalAdmin.previewEmpty": "Nothing written in this language yet.",
  "legalAdmin.placeholder":
    "# Legal notice\n\nInformation pursuant to § 5 DDG…\n\nMarkdown: # heading, **bold**, - list, [link](https://example.org)",
  "legalAdmin.germanHint":
    "The binding version. Markdown is supported; HTML is shown as plain text rather than rendered, so a public page cannot be made to run a script.",
  "legalAdmin.englishHint":
    "A courtesy translation, and optional. Readers of English are shown the German text with a note until one exists — a current document in the wrong language beats a stale one in the right one.",
  "legalAdmin.emptyMeansDefault": "Clearing the German text unpublishes the document.",
  "legalAdmin.saved": "Saved. The public page shows the new text immediately.",
  "oidc.loadFailed": "The providers could not be loaded.",
  "oidc.saveFailed": "Saving failed.",
  "oidc.deleteFailed": "Deleting failed.",
  "oidc.title": "External sign-in providers",
  "oidc.subtitle": "OpenID Connect. Providers are disabled by default.",
  "oidc.add": "Add a provider",
  "oidc.loading": "Loading providers…",
  "oidc.enabled": "enabled",
  "oidc.hasSecret": "Client secret stored",
  "oidc.noSecret": "No client secret (public client)",
  "oidc.editing": "Editing {slug}",
  "oidc.newProvider": "New provider",
  "oidc.fieldSlug": "Slug (URL part)",
  "oidc.fieldDisplayName": "Display name",
  "oidc.fieldIssuer": "Issuer",
  "oidc.fieldClientId": "Client ID",
  "oidc.fieldClientSecret": "Client secret",
  "oidc.fieldRedirectUri": "Redirect URI",
  "oidc.fieldScopes": "Scopes",
  "oidc.secretUnchanged": "•••••••• (leave unchanged)",
  "oidc.toggleEnabled": "Enabled",
  "oidc.toggleEnabledHint": "Appears on the sign-in screen.",

  // ── Profile and import ──────────────────────────────────────────────────
  "profile.title": "Account and profile settings",
  "profile.subtitle": "Manage your account, security settings and one-click data deletion.",
  "profile.tenantIsolated": "Tenant isolated",
  "profile.defaultUser": "User",
  "profile.defaultInitial": "U",
  "profile.role": "Role: {role}",
  "profile.username": "Username",
  "profile.email": "Email address",
  "profile.workspaceName": "Workspace name",
  "profile.workspaceAdminOnly": "Only owners and administrators can change the workspace name.",
  "profile.save": "Save profile",
  "profile.saving": "Saving…",
  "profile.saved": "Profile saved.",
  "profile.savedAndSessionRefreshed": "Profile saved and session refreshed.",
  "profile.saveFailed": "Saving the profile failed.",
  "profile.passwordMismatch": "The new passwords do not match.",
  "profile.passwordFailed": "Changing the password failed.",
  "profile.passwordChanged": "Password changed.",
  "profile.wipeFailed": "Deleting the data points failed.",
  "profile.wipeDone": "Deleted {count} data points from this workspace.",
  "profile.deleteAccountFailed": "Deleting the account failed.",
  "profile.gdprTitle": "One-click deletion (GDPR Art. 17)",
  "profile.gdprBadge": "Right to erasure active",
  "profile.gdprBody":
    "Under GDPR Article 17 you can delete every data point stored on this platform, or your whole account, in one click.",
  "profile.wipeButton": "Delete all data points",
  "profile.deleteAccountButton": "Delete account and all data",
  "profile.changePassword": "Change password",
  "profile.passwordPlaceholder": "••••••••",
  "profile.passwordMinimum": "At least 6 characters",
  "profile.passwordRepeat": "Repeat password",
  "profile.confirm": "Confirm",
  "profile.changing": "Changing…",
  "profile.encryptionNote":
    "Connector tokens are encrypted with Fernet AES-256 before they are stored.",
  "profile.appearance": "Appearance and language",
  "profile.language": "Interface language",
  "profile.theme": "Theme",
  "profile.workspaceDetails": "Workspace and tenant ID",
  "profile.tenantId": "Tenant ID (UUID)",
  "profile.copy": "Copy",
  "profile.copied": "Copied",
  "profile.encryptedSecrets": "AES-256 encrypted secrets",
  "profile.sessionTitle": "Session and sign-out",
  "profile.signOut": "Sign out of this account",
  "profile.wipeConfirmTitle": "Delete all data points?",
  "profile.wipeConfirmBody": "This deletes every imported data point in your workspace.",
  "profile.wipeConfirmAction": "Yes, delete all data points",
  "profile.wipeRunning": "Deleting data…",
  "profile.deleteAccountTitle": "Delete the whole account?",
  "profile.deleteAccountBody":
    "This irreversibly deletes every data point, connector token and share belonging to your account (GDPR Art. 17).",
  "profile.deleteAccountAction": "Delete irreversibly",
  "profile.deleteAccountRunning": "Deleting the account…",
  "profile.legalTitle": "Legal",
  "profile.documentation": "Documentation",
  "profile.defaultWorkspace": "{name}'s Workspace",
  "profile.privacyLead": "Which data is processed, on what basis, and how to delete it",
  "import.days": "{count} days",
  "import.title": "Import data — {name}",
  "import.from": "From",
  "import.to": "To",
  "import.suggestion": "Suggestion:",
  "import.windowSuggested": "Core selected a safe range based on the connector history.",
  "import.modeLegend": "Mode",
  "import.smartLabel": "Smart (recommended)",
  "import.forceBody": "The whole period is processed again.",
  "import.forceWarning":
    "Force imports cost considerably more processing and produce duplicate events. Idempotency still prevents duplicate data points,",
  "import.previewLegend": "Preview",
  "import.howItWorks": "How smart and force imports work",
  "import.recent": "Recent imports ({count})",
  "import.runCounts":
    "{accepted} new · {duplicate} duplicates · {rejected} rejected · {unsupported} unsupported fields",
  "import.running": "Import running",
  "import.loadingCore": "Loading data in Core",
  "import.progressOf": "{done} of {total} events processed by Core",
  "import.progressCounted": "{count} events processed by Core so far",
  "import.typicallySeconds": "usually about {count} s",
  "import.typicallyMinutes": "usually about {count} min",
  "import.passiveExplainer":
    "This connector receives data when your device sends it, so there is nothing to start here. What a push import does have is shown below: how far the current one has got, and what earlier ones did.",
  "import.uploadLegend": "Import an export file",
  "import.uploadHintAppleHealth":
    "In the Health app, open your profile and choose “Export All Health Data”. Upload the export.zip you receive here — it holds your whole history, workouts and GPS routes included.",
  "import.uploadHintWhoop":
    "In the Whoop app, request your data export under Account. Upload the ZIP of CSVs that arrives by email here.",
  "import.uploadChoose": "Choose an export file",
  "import.uploadStart": "Upload",
  "import.uploading": "Uploading…",
  "import.uploadProgress": "Upload progress",
  "import.uploadProgressPercent": "{percent}% uploaded",
  "import.uploadAccepted": "The file has arrived and is being read. Progress appears above.",
  "import.uploadFailed": "The file could not be uploaded.",
  "import.uploadInParts":
    "The file is being sent in parts, so a large export gets through. You can close this dialog — the upload keeps going.",
  "import.minimize": "Minimise",
  "import.minimizeHint": "Close the dialog. The upload keeps running and stays visible.",
  "import.uploadReimportNote":
    "The same file can be uploaded again without creating duplicates: a reading already stored stays one reading.",
  "import.planFailed": "The import plan could not be loaded.",
  "import.startFailed": "The import could not be started.",
  "import.nothingToDo": "Nothing to do — the period is already complete.",
  "import.queued": "Import queued.",
  "import.subtitle": "Check and adjust the period before the import starts.",
  "import.close": "Close the dialog",
  "import.smartHint": "Periods that are already complete are skipped. Only the",
  "import.forceLabel": "Force everything",
  "import.forceHint":
    "but the run takes longer and uses more of the provider's rate limit. It is marked as force in the import log.",
  "import.noAnalysis": "No analysis available yet.",
  "import.tooIrregular": "The existing data is too irregular for a confident",
  "import.willSkip": "Will be skipped",
  "import.willImport": "Will be imported",
  "import.nothingToImportShort": "Nothing to import.",
  "import.start": "Start the import",
  "import.nothingToImport": "Nothing to import",

  // ── Global importer run overview ───────────────────────────────────────
  "importOverview.title": "All import runs",
  "importOverview.subtitle":
    "See every connector together and distinguish queued work, importer activity, Core loading and completed runs.",
  "importOverview.refresh": "Refresh runs",
  "importOverview.active": "Active now",
  "importOverview.loadingCore": "Loading in Core",
  "importOverview.completed": "Completed",
  "importOverview.failed": "Failed",
  "importOverview.loading": "Loading import runs…",
  "importOverview.loadFailed": "The import run overview could not be loaded.",
  "importOverview.empty": "No import runs have been recorded yet.",
  "importOverview.progress": "{processed} of {total} events processed",
  "importOverview.quality": "{rejected} rejected · {unsupported} unsupported fields",
  "importOverview.loadingMore": "Loading older runs…",
  "importOverview.loadMore": "Load older runs",

  // ── Upload banner (an upload that outlived its dialog) ──────────────────────
  "upload.title": "Uploading — {name}",
  "upload.doneTitle": "Upload complete — {name}",
  "upload.errorTitle": "Upload failed — {name}",
  "upload.cancelledTitle": "Upload cancelled — {name}",
  "upload.sentOf": "{done} of {total} MB · {percent}%",
  "upload.progressPercent": "{percent}% uploaded",
  "upload.assembling": "All parts have arrived. The importer is reading the archive…",
  "upload.doneBody": "The archive is being read. The connector shows how the import is going.",
  "upload.errorBody": "The upload stopped before the file was complete.",
  "upload.cancelledBody": "The parts that had arrived were deleted.",
  "upload.cancel": "Cancel the upload",
  "upload.resume": "Continue",
  "upload.dismiss": "Dismiss",

  // ── Import duration ─────────────────────────────────────────────────────
  "import.hours": "{count} h",

  // ── Data explorer ───────────────────────────────────────────────────────
  "explorer.title": "Raw data explorer",
  "explorer.subtitle":
    "Explore server-aggregated metric series and the newest raw data points stored for this workspace. Saved views live in PostgreSQL.",
  "explorer.refresh": "Refresh the data",
  "explorer.savedViews": "Saved views",
  "explorer.saveCurrent": "Save the current view",
  "explorer.viewNamePlaceholder": "Name of the view…",
  "explorer.deleteView": "Delete this view",
  "explorer.noViews":
    "No saved views yet. Configure the filters and press “Save the current view”.",
  "explorer.source": "Source:",
  "explorer.allSources": "All sources",
  "explorer.pointLimitReached":
    "Showing the newest {count} points for {metrics}. Narrow the period to see everything that is stored.",
  "explorer.colStorage": "Storage",
  "explorer.storageHint":
    "Storage sets how finely a metric is kept when it arrives. It applies to future imports only — points already stored are untouched.",
  "explorer.storageApply": "Apply",
  "explorer.storageIsDefault": "Registry default",
  "explorer.storageIsOverride": "Set for this workspace",
  "explorer.resolutionRaw": "Raw",
  "explorer.resolutionSecond": "Second",
  "explorer.resolutionMinute": "Minute",
  "explorer.resolutionHour": "Hour",
  "explorer.resolutionDay": "Day",
  "explorer.period": "Period:",
  "explorer.customStart": "Start date",
  "explorer.customEnd": "End date",
  "explorer.selectAll": "Select all",
  "explorer.searchPlaceholder":
    "Full-text search across the raw data (food name, category, metric name or JSON metadata…)",
  "explorer.colSource": "Source",
  "explorer.colValue": "Value",
  "explorer.empty": "No data points for the current query.",

  // ── Data explorer: views ────────────────────────────────────────────────
  "explorer.tabChart": "Chart",
  "explorer.tabRaw": "Raw data points",
  "explorer.tabOverview": "Metrics",

  // ── Data explorer: metric picker ────────────────────────────────────────
  "explorer.metrics": "Metrics:",
  "explorer.metricsNone": "No metric selected",
  "explorer.metricsSelected_one": "{count} metric",
  "explorer.metricsSelected_other": "{count} metrics",
  "explorer.metricFilterPlaceholder": "Filter metrics…",
  "explorer.clearSelection": "Clear the selection",
  "explorer.metricsEmpty": "No metrics stored yet.",
  "explorer.metricsNoMatch": "No metric matches that filter.",

  // ── Data explorer: raw point log ────────────────────────────────────────
  "explorer.rawCount_one": "{count} match",
  "explorer.rawCount_other": "{count} matches",
  "explorer.rawTruncated": "Showing the newest {shown} of {total} matches.",
  "explorer.liveQuery": "Live TimescaleDB query",
  "explorer.mixedUnits":
    "These metrics are measured in different units ({units}) and share one axis, so a series with smaller values is flattened against a larger one. Compare them one unit at a time, or use the metric overview.",
  "explorer.seriesQueryNote":
    "Each selected metric is loaded separately as a recent server-side series. Metric-aware aggregation is applied by the API; missing buckets remain empty.",
  "explorer.rawSeriesQueryNote":
    "Each selected metric is queried separately, newest first. Connector instance IDs are used when available, and the table is limited per selected metric for browser performance.",
  "explorer.seriesMetricLabel": "{metric} · {aggregation}",
  "explorer.seriesMetricSourceLabel": "{metric} · {source} · {aggregation}",
  "explorer.scopeActive": "Loaded on its own: {metric}",
  "explorer.scopeClear": "Back to all metrics",
  "explorer.colTimestamp": "Timestamp",
  "explorer.colId": "ID",
  "explorer.colIdempotencyKey": "Idempotency key",
  "explorer.colMetric": "Metric",
  "explorer.colMetadata": "Metadata (JSON)",
  "explorer.colDetails": "Details",
  "explorer.inspect": "Inspect the JSON",
  "explorer.inspectorTitle": "Raw data point",
  "explorer.inspectorMetadata": "Metadata (JSONB)",

  // ── Data explorer: metric overview ──────────────────────────────────────
  "explorer.overviewHint":
    "Every metric type this workspace holds, counted over the whole history. Open one to read its newest raw data points.",
  "explorer.overviewEmpty": "No metrics stored yet, so there is nothing to summarise.",
  "explorer.overviewFailed": "The metric overview could not be loaded.",
  "explorer.colUnit": "Unit",
  "explorer.colPoints": "Data points",
  "explorer.colTypical": "Meaningful value",
  "explorer.colRange": "Min / max",
  "explorer.colLatest": "Latest",
  "explorer.showRaw": "Raw data points",
  "explorer.unregistered": "Not in the registry",
  "explorer.aggAverage": "Average",
  "explorer.aggSum": "Total",
  "explorer.aggMax": "Maximum",
  "explorer.aggLast": "Latest value",

  // ── Remaining OIDC and profile fields ───────────────────────────────────
  "oidc.emptyState":
    "No provider configured yet. Signing in with an email address and password works regardless.",
  "oidc.toggleSignup": "Allow sign-up",
  "oidc.toggleSignupHint": "Creates a new account when the identity is unknown.",
  "oidc.toggleVerified": "Require a verified email",
  "oidc.toggleVerifiedHint": "Recommended. Without verification an address is not an identity.",
  "oidc.issuerHint":
    "The issuer is checked when saving: the discovery document has to be reachable and name the same issuer.",
  "profile.currentPassword": "Current password",
  "profile.newPassword": "New password",

  // ── Connector dialog ────────────────────────────────────────────────────
  "modal.catNutrition": "Nutrition & diary",
  "modal.desc.yazio":
    "Active: the importer fetches meals, calories and nutrients from your Yazio diary.",
  "modal.desc.whoop":
    "Active: the importer fetches recovery score, HRV, sleep stages, resting heart rate and strain.",
  "modal.desc.apple_health":
    "Passive: Health Auto Export sends steps, heart rate, sleep stages and workouts to your webhook.",
  "modal.desc.streak":
    "Passive: Streak 2.0 sends workouts, sets, reps and weights to your REST webhook.",
  "modal.desc.dawarich":
    "Active: the importer fetches locations, GPS points and movement traces from your Dawarich server.",
  "modal.desc.home_assistant":
    "Active: reads temperature, humidity, light and any other exposed sensor state.",
  "modal.desc.weather":
    "Active: imports local weather time series through an Open-Meteo compatible API.",
  "modal.desc.calendar": "Active: imports the appointments you expose and the busy time per day.",
  "modal.desc.github": "Active: reads your own contribution activity with a fine-grained access token.",
  "modal.needEmailPassword": "Please enter both an email address and a password.",
  "modal.needYazioToken": "Please enter a Yazio bearer access token.",
  "modal.needWhoopToken": "Please enter a WHOOP access token.",
  "modal.needWhoopGrantComplete":
    "Renewal needs all three together: client ID, client secret and refresh token. Leave all three empty to set the connector up with the access token alone.",
  "modal.whoopTokenLabel": "WHOOP access token",
  "modal.pasteWhoopToken": "Paste the WHOOP access token here",
  "modal.whoopGrantTitle": "Keep it working past the first hour",
  "modal.whoopGrantHint":
    "A WHOOP access token expires after about an hour, and syncs run every few hours. With the OAuth application's client ID, its secret and a refresh token, the token is renewed before it expires. Both secrets are stored encrypted and never reach the importer.",
  "modal.whoopGrantKept": "Leave a field empty to keep what is stored.",
  "modal.whoopClientIdLabel": "Client ID",
  "modal.whoopClientSecretLabel": "Client secret",
  "modal.whoopRefreshTokenLabel": "Refresh token",
  "modal.needDawarichKey": "Please enter the Dawarich API key.",
  "modal.needGithubToken": "Please enter a GitHub personal access token.",
  "modal.githubTokenLabel": "GitHub personal access token",
  "modal.pasteGithubToken": "github_pat_… or ghp_…",
  "modal.githubTokenHint":
    "A fine-grained token with Contents: read and Metadata: read on the repositories you want counted. Add Followers: read for the follower count.",
  "modal.githubPerRepoLabel": "Per-repository breakdown",
  "modal.githubPerRepoHint":
    "Store one series per repository alongside the account-wide totals. Quiet days are omitted there.",
  "modal.githubPerRepoKept":
    "The stored setting is kept unless you change this box.",
  "modal.needCalendarUrl": "Please enter the URL of your calendar feed (.ics).",
  "modal.calendarUrlScheme": "The calendar URL has to start with http:// or https://.",
  "modal.needBaseUrl": "Please enter the HTTPS base URL of the provider API.",
  "modal.baseUrlLabel": "Base URL",
  "modal.calendarUrlLabel": "Calendar feed URL",
  "modal.displayNameLabel": "Name",
  "modal.displayNamePlaceholder": "e.g. Personal",
  "modal.displayNameHint":
    "Shown on the connector card. You can set up the same provider more than once — the name is what tells them apart.",
  "modal.needDisplayName": "Please give this connector a name.",
  "modal.credentialsStoredBody":
    "You can change the polling interval and period without entering the credentials again.",
  "modal.tokenLabel": "Access token",
  "modal.tokenPlaceholder": "Bearer token / API key",
  "modal.keepTokenPlaceholder": "•••••••• (keep the token)",
  "modal.setupGuide": "Setup guide",
  "modal.weatherPlaceLabel": "Location",
  "modal.weatherPlacePlaceholder": "City or place name",
  "modal.weatherSearch": "Search",
  "modal.weatherSearching": "Searching…",
  "modal.weatherNoPlaces": "No place of that name was found.",
  "modal.weatherSearchFailed": "The place could not be looked up. Enter the coordinates directly.",
  "modal.weatherChosenPlace": "Using {place}",
  "modal.weatherLatitude": "Latitude",
  "modal.weatherLongitude": "Longitude",
  "modal.weatherNeedCoordinates":
    "Please choose a location, or enter latitude and longitude yourself.",
  "modal.weatherCoordinatesRange":
    "Latitude must be between -90 and 90, longitude between -180 and 180.",
  "modal.weatherModeGuided": "Guided",
  "modal.weatherModeCustom": "Own URL",
  "modal.weatherRequestUrlLabel": "Full request URL",
  "modal.weatherRequestUrlHint":
    "Sent exactly as written, query included — so a URL copied from the provider's own documentation works, including the archive endpoint for periods further back than the forecast API reaches. The import period is added only where you have not set one.",
  "modal.weatherNeedRequestUrl": "Please enter a complete URL starting with http:// or https://.",
  "modal.weatherBaseUrl": "Provider URL",
  "modal.weatherBaseUrlHint":
    "Open-Meteo is preset and needs no API key. Replace it only for a self-hosted or commercial endpoint.",
  "modal.needApiKey": "Please enter a valid API key for {provider}.",
  "modal.needApiKeyOrGenerate": "Please enter a valid API key for {provider}, or generate one.",
  "modal.saved": "{provider} settings saved.",
  "modal.saveFailed": "The configuration could not be saved.",
  "modal.networkError": "Network error: {message}",
  "modal.serverUnreachable": "server unreachable",
  "modal.backToChoice": "Back to the list",
  "modal.pickSource": "Choose a data source",
  "modal.editProvider": "Edit {provider}",
  "modal.connectProvider": "Connect {provider}",
  "modal.guideFor": "Open the guide for {provider}",
  "modal.pickHint":
    "Pick an importer. The badge says whether it polls a service itself or receives data from it:",
  "modal.available": "Available",
  "modal.activeShort": "Active · polls",
  "modal.passiveShort": "Passive · receives",
  "modal.passiveTitle": "Passive importer · data is delivered to you",
  "modal.activeTitle": "Active importer · polls the service itself",
  "modal.passiveBody":
    "You store the webhook address and the header key. The external service sends new data as it happens; no sync interval is needed.",
  "modal.activeBody":
    "You store the credentials. The importer polls the external service on the configured interval and period.",
  "modal.credentialsStored": "Credentials are stored (Fernet AES-256)",
  "modal.keepCredentials": "Keep the stored credentials…",
  "modal.keepUnchanged": "•••••••• (leave unchanged)",
  "modal.keepCredentialsShort": "•••••••• (keep the credentials)",
  "modal.pasteYazioToken": "Paste your Yazio bearer token here",
  "modal.keepApiKey": "•••••••• (keep the API key)",
  "modal.pasteDawarichKey": "Paste your Dawarich API key here",
  "modal.icsHint":
    "Public and private ICS feeds (Outlook, Google, Nextcloud) all work, and none of them need an API key. A private feed address is itself the secret: it is stored encrypted and never logged.",
  "modal.intervalSection": "Edit the polling interval and period",
  "modal.everyHour": "Every hour",
  "modal.everyNHours": "Every {count} hours",
  "modal.everyNHoursDefault": "Every {count} hours (default)",
  "modal.daily": "Daily (24 h)",
  "modal.weekly": "Weekly (168 h)",
  "modal.importPeriod": "Import period",
  "modal.lastNDays": "Last {count} days",
  "modal.lastNDaysDefault": "Last {count} days (default)",
  "modal.lastNHours": "Last {count} hours",
  "modal.lastNHoursDefault": "Last {count} hours (default)",
  "modal.guide": "Guide",
  "modal.syncFrequency": "Sync frequency",
  "modal.yazioTokenMode": "Enter a bearer token",
  "modal.yazioTokenOptional": "Bearer token (optional)",
  "modal.yazioLoginMode": "Yazio login",
  "modal.yazioLoginOptional": "Yazio login (optional)",
  "modal.modeConnect": "Connect now",
  "modal.modeFile": "Import a file",
  "modal.modeConnectHint": "The connector fetches your data itself, on the schedule set below.",
  "modal.modeFileHint":
    "No account connection: you upload the export this provider gives you, and it is read into this connector. You can still connect it later — the same data stays one series.",
  "modal.fileFlowLead": "Fed by files:",
  "modal.fileFlowBody":
    "Nothing is polled and no credential is stored. After saving, open Upload on the connector and choose your export.",
  "modal.passiveFlowLead": "Passive data flow:",
  "modal.passiveFlowBody":
    "Once saved, the configured app sends data to the URL shown above. New data is processed without anyone polling for it.",
  "modal.back": "Back",
  "modal.saving": "Saving…",
  "modal.saveSettings": "Save the settings",
  "modal.saveConnection": "Save the connection",

  // ── Connector categories ────────────────────────────────────────────────
  "modal.catRecovery": "Recovery & sleep",
  "modal.catVitals": "Fitness & vitals",
  "modal.catStrength": "Strength training",
  "modal.catLocation": "Location & GPS",
  "modal.catSmartHome": "Smart home",
  "modal.catEnvironment": "Environment",
  "modal.catRoutine": "Routine & stress",

  // ── Analysis ────────────────────────────────────────────────────────────
  "analysis.tabOverview": "Overview",
  "analysis.tabCorrelations": "Relationships",
  "analysis.tabAnomalies": "Outliers",
  "analysis.tabQuality": "Data quality",
  "analysis.loadFailed": "The analyses could not be loaded.",
  "analysis.computing": "Computing the analyses…",
  "analysis.title": "Relationships & patterns",
  "analysis.subtitleTail": "Relationships — not causes.",
  "analysis.window": "Period",
  "analysis.fromPercent": "from {percent} %",
  "analysis.onlySignificant": "statistically significant only",
  "analysis.disclaimer":
    "Every result describes a statistical relationship, not cause and effect. None of it is medical advice.",
  "analysis.minStrength": "Minimum strength",
  "analysis.source": "Source",
  "analysis.allSources": "All sources",
  "analysis.all": "all",
  "analysis.howToRead": "How to read these analyses",
  "analysis.noData":
    "There is no data to analyse yet. Set up a connector and import at least two weeks.",
  "analysis.excludedForQuality": "{count} hidden because the data is too thin",
  "analysis.ambiguousSources":
    "{count} metric(s) are reported by more than one connector. One of them answers, because adding two would count the same value twice.",
  "analysis.ambiguousUnresolved":
    "{count} metric(s) come from several connectors and no primary source is set, so they were left out.",
  "analysis.primaryByCoverage": "chosen automatically — most complete",
  "analysis.primaryByPreference": "your choice",
  "analysis.chooseSource": "Choose source",

  // ─── Precomputed reports ──────────────────────────────────
  "report.computedAt": "Computed {timestamp}",
  "report.neverComputed": "Not computed yet",
  "report.running": "Computing…",
  "report.stale": "New data since",
  "report.deferred": "Updates overnight",
  "report.deferredTitle":
    "New data has arrived. A window this long is recomputed during the night rather than while you are working — recompute now if you would rather not wait.",
  "report.recompute": "Recompute",
  "report.failed": "The last computation failed; the previous result remains available.",
  "report.error.report_failed":
    "The last computation failed; the previous result remains available.",
  "report.error.insights_failed":
    "The analysis could not be computed. The previous result remains available.",
  "report.error.insights_rejected":
    "The analysis service asked for something this workspace's data does not allow, and repeating it will not help. The previous result remains available; the reason is in the analysis service log.",
  "report.error.report_load_failed":
    "The saved report could not be loaded. Check the connection and try again.",
  "report.error.report_timeout":
    "The analysis was started but did not finish in time. It will be retried after the next import; a shorter period usually completes.",
  "report.error.report_never_claimed":
    "No analysis worker picked this report up. The analysis service is probably stopped or unreachable — waiting longer will not help.",
  "report.error.report_refresh_failed":
    "The report could not be started. Check the connection and try again.",
  "report.pendingFirstRun":
    "This is computed in the background after an import. Start it now to see it straight away.",

  // ─── Background jobs (notification bell) ──────────────────
  "jobs.title": "Activity",
  "jobs.bell": "Background activity",
  "jobs.bellWithCount": "Background activity, {count} new",
  "jobs.refresh": "Refresh",
  "jobs.empty": "Nothing has run in the last two weeks.",
  "jobs.loadFailed": "The activity list could not be loaded.",
  "jobs.running": "Running…",
  "jobs.pointsStored": "{count} values stored",
  "jobs.overDays": "Over {days} days",
  "jobs.subject.insights": "Analysis",
  "jobs.subject.gaps": "Gap scan",
  "jobs.subject.conflicts": "Conflict scan",
  "jobs.subject.day": "Daily story",
  "jobs.trigger.manual": "Started by you",
  "jobs.trigger.scheduled": "Scheduled",
  "jobs.trigger.nightly": "Overnight",
  "jobs.trigger.webhook": "Pushed by provider",
  "jobs.trigger.upload": "From an upload",
  // ── Import and report run outcomes ────────────────────────────────────
  // Core sends a stable `code` plus its own English sentence (rule 17). The
  // sentence is the fallback for a code this build does not know; it is not
  // meant to be the normal path, which is what it had become — the bell knew
  // two codes and Core emits eight, so every import notification read English
  // in a German interface.
  "jobs.code.sync_skipped": "Nothing new — the period was already covered.",
  "jobs.code.sync_queued": "Queued for import.",
  "jobs.code.sync_in_flight": "An import for this connector was already running.",
  "jobs.code.sync_not_scheduled":
    "This connector has no scheduled import; it receives data by webhook or upload.",
  "jobs.code.sync_plan_failed": "Could not work out which period to import.",
  "jobs.code.sync_failed": "The import did not finish.",
  "jobs.code.core_ingest_delivery_failed":
    "The importer published data that could not be handed to storage, after {attempts} attempt(s).",
  "jobs.code.report_timeout": "Started but did not finish in time",
  "jobs.code.report_never_claimed": "No analysis worker picked it up",

  // ─── Primary source selection ─────────────────────────────
  "sources.title": "Metrics from several connectors",
  "sources.intro":
    "These metrics arrive from more than one connector. Values are never added together — one connector answers, and you can say which.",
  "sources.none": "No metric is reported by more than one connector.",
  "sources.automatic": "Automatic (most complete)",
  "sources.saveFailed": "Could not be saved. Please try again.",
  "sources.samples": "{count} values",
  "analysis.allMetricsQualify": "every metric meets the minimum requirements",
  "analysis.significantRelationships": "Significant relationships",
  "analysis.ofPairsChecked": "of {count} pairs checked",
  "analysis.unusualDays": "Unusual days",
  "analysis.outsideNormal": "outside your own normal range",
  "analysis.noneMatchFilters":
    "No relationships match the filters. That is a valid result — not every metric relates to another.",
  "analysis.laggedTitle": "Time-shifted relationships",
  "analysis.laggedTail":
    "A value from one day is compared with another metric a few days later. A sequence in time is no evidence of a cause.",
  "analysis.laggedExploratory":
    "Exploratory only: these lag p-values are unadjusted across the tested lags and pairs. A time order is not causation.",
  "analysis.lagDays": "+{count} days",
  "analysis.sameDirection": "same direction",
  "analysis.oppositeDirection": "opposite direction",
  "analysis.tooFewForTrend": "Too few days for a statement about a trend.",
  "analysis.trendStats": "Mean {mean} · R² {r2} · n={n} days",
  "analysis.tooFewForNormalRange": "Too few days to establish a personal normal range.",
  "analysis.anomalyBasis":
    "Based on the median and median absolute deviation (MAD) over {days} days. Unusual means unusual for you, not automatically medically concerning.",
  "analysis.tooFewForWeekly": "At least two weeks of data are needed to see weekly patterns.",
  "analysis.colDays": "Days",
  "analysis.sufficient": "sufficient",
  "analysis.tooThin": "too thin",
  "analysis.scaleStrongOpposite": "strongly opposite",
  "analysis.scaleNone": "no relationship",
  "analysis.scaleStrongSame": "strongly aligned",
  "analysis.scaleLabel":
    "Colour scale from strongly opposite through no relationship to strongly aligned",
  "analysis.scaleMin": "−1.0",
  "analysis.scaleMax": "+1.0",
  "analysis.scaleEnds": "opposite ← → aligned",
  "analysis.matrixHint":
    "Each cell shows the correlation coefficient r from −1 to +1. Empty cells have no eligible result for the current data and filters.",
  "analysis.coefficientShort": "r = {value}",
  "analysis.explainerTitle": "How to read these relationships",
  "analysis.explainerWhatTitle": "What it shows",
  "analysis.explainerWhat":
    "Each pair shows whether two metrics tend to be higher or lower on the same days. It describes an association, not a cause.",
  "analysis.explainerMethodTitle": "How it is calculated",
  "analysis.explainerMethod":
    "Pearson and Spearman are compared on shared days. The more conservative coefficient is shown and q-values adjust for the number of pairs.",
  "analysis.explainerLimitsTitle": "What it cannot tell you",
  "analysis.explainerLimits":
    "Missing data, a third factor, seasonality, and repeated measurements can all create a pattern. Correlation cannot explain why it occurs.",
  "analysis.matrixMobileHint":
    "On a small screen, each relationship is shown as a readable card. Select one for the full calculation and limitations.",
  "analysis.matrixMobileAria": "Open details for {first} and {second}",
  "analysis.matrixCellTitle": "{first} and {second}: coefficient {value}; q-value {q}",
  "analysis.matrixCellTitleRaw": "{first} and {second}: coefficient {value}; raw p-value {q}",
  "analysis.matrixCellAria": "{first} and {second}: correlation coefficient {value}",
  "analysis.strongestTitle": "Strongest relationships",
  "analysis.matrixTitle": "Correlation matrix",
  "analysis.matrixSize": "{count} metrics",
  "analysis.runTitle": "Which run this is",
  "analysis.runSummary": "{days} days · {source}",
  "analysis.runNote":
    "Changing the window or the source starts a new analysis run, which takes a few minutes. The filters below only change what is shown.",
  "analysis.laggedTruncated": "Showing {shown} of {total}.",
  "analysis.matrixAria": "Correlation matrix of metrics",
  "analysis.interpretationTitle": "Interpretation",
  "analysis.sharedDays": "Shared days: {count}",
  "analysis.periodLabel": "Period:",
  "analysis.coverageLabel": "Coverage:",
  "analysis.calculationTitle": "Calculation",
  "analysis.pearsonLabel": "Pearson (linear):",
  "analysis.spearmanLabel": "Spearman (rank):",
  "analysis.pValueLabel": "Raw p-value:",
  "analysis.qValueLabel": "q-value:",
  "analysis.qValueShort": "q {value}",
  "analysis.pValueShort": "p {value}",
  "analysis.sampleSize": "n={count}",
  "analysis.bhAdjustment": "Benjamini–Hochberg adjusted",
  "analysis.analysisVersionLabel": "Analysis version:",
  "analysis.computedLabel": "Computed:",
  "analysis.metricLabel": "Metric",
  "analysis.statusLabel": "Status",
  "analysis.qualityHint":
    "Analyses run only on metrics with enough data. Everything else is deliberately hidden rather than shown weakly.",
  "analysis.provenanceSummary":
    "Period {start} – {end} · Sources: {sources} · analysis version {version} · computed {computed}",
  "analysis.provenanceTitle": "Data basis",
  "analysis.sources": "Sources: {list}",
  "analysis.significant": "significant after adjustment (q ≤ 0.05)",
  "analysis.notSignificant": "not significant after adjustment",
  "analysis.limitsTitle": "Limitations",
  "analysis.limitsBody":
    "A relationship is not a cause. Both values may depend on a third factor nobody recorded.",
  "analysis.sparklineLabel": "Rolling 7-day mean",
  "analysis.footerSources": "Sources: {list} · analysis version",
  "analysis.strengthDisclaimer":
    "An estimated one-rep max uses Epley's formula on the heaviest set; it is an estimate, not a measurement, and is not calculated above ten repetitions.",
  "analysis.anomalyDirection.unusually_high": "unusually high",
  "analysis.anomalyDirection.unusually_low": "unusually low",
  "analysis.direction.higher": "higher",
  "analysis.direction.lower": "lower",
  "analysis.direction.higherCorrelation": "higher",
  "analysis.direction.lowerCorrelation": "lower",
  "analysis.direction.higherRoutine": "higher",
  "analysis.direction.lowerRoutine": "lower",
  "analysis.strength.very_weak": "very weak",
  "analysis.strength.weak": "weak",
  "analysis.strength.moderate": "moderate",
  "analysis.strength.strong": "strong",
  "analysis.strength.very_strong": "very strong",
  "analysis.interpretation.correlation_association":
    "{metric_a} and {metric_b} tend to move together: higher values for {metric_a} occur on average with {direction} values for {metric_b} ({strength}, {sample_size} shared days). This is an association, not a cause.",
  "analysis.interpretation.lagged_association":
    "{metric_a} tends to move together with {metric_b} {lag_days} day(s) later ({strength}, {sample_size} shared days). This exploratory ordering is not evidence of a cause.",
  "analysis.interpretation.trend_summary":
    "Across {sample_size} days, the course is {direction} (about {change_pct} % over the period). Treat this as a descriptive pattern, not a cause.",
  "analysis.interpretation.anomaly_summary":
    "Your typical range is {normal_range_low} to {normal_range_high}; {anomaly_count} of {sample_size} days fall clearly outside it. This is a personal signal, not a diagnosis.",
  "analysis.interpretation.routine_weekend_difference":
    "At the weekend, the value averages {difference_pct} % {direction} than on weekdays.",
  "analysis.interpretation.routine_no_weekend_difference":
    "There is no clear weekend–weekday difference in this data.",
  "analysis.interpretation.routine_weekday_only":
    "There are not enough weekend observations to compare weekday and weekend values.",
  "analysis.interpretation.period_comparison":
    "The second period is {difference_pct} % {direction} on average. A difference between periods does not identify a cause.",
  "analysis.caveat.pearson_spearman_disagree":
    "Pearson and Spearman differ noticeably. Outliers or a non-linear pattern may be involved.",
  "analysis.caveat.small_overlap":
    "Only {sample_size} shared days are available, so this result carries little weight.",
  "analysis.caveat.raw_not_significant":
    "The raw test is not statistically significant; the pattern may be chance.",
  "analysis.caveat.bh_not_significant_raw_below_alpha":
    "The raw p-value is below 0.05, but the result is not significant after correcting for all tested pairs.",
  "analysis.caveat.bh_not_significant":
    "The result is not statistically significant after correcting for all tested pairs.",

  // ── Analysis tiles ──────────────────────────────────────────────────────
  "analysis.usableMetrics": "Metrics that can be analysed",

  // ── Analysis sections ───────────────────────────────────────────────────
  "analysis.tabTrends": "Trends",
  "analysis.tabRoutines": "Routines",

  // ── AI chat ────────────────────────────────────────────────────────────────
  "chat.title": "AI chat",
  "chat.subtitle": "Ask questions about your personal metrics and patterns.",
  "chat.statusChecking": "Checking chat availability…",
  "chat.statusReady": "ChatGPT {plan}",
  "chat.newConversation": "New chat",
  "chat.unavailableTitle": "Codex is not available",
  "chat.unavailableBody":
    "Install the Codex CLI next to the Analysis service or enable it in the service image to use chat.",
  "chat.loginTitle": "Connect your ChatGPT subscription",
  "chat.loginBody":
    "Sign in through the official Codex device flow. The platform never receives your password and stores the Codex credential state only as an encrypted blob.",
  "chat.loginAction": "Connect ChatGPT",
  "chat.deviceInstruction": "Open the sign-in page and enter this one-time code.",
  "chat.deviceCodeLabel": "One-time code",
  "chat.copyCode": "Copy the one-time code",
  "chat.openLogin": "Open ChatGPT sign-in",
  "chat.waitingForLogin": "This page will continue automatically after sign-in.",
  "chat.welcomeTitle": "What would you like to understand?",
  "chat.welcomeBody":
    "Ask about trends, data quality, unusual values, or relationships between your metrics. Data is read through tenant-scoped, read-only tools.",
  "chat.userMessage": "Your message",
  "chat.assistantMessage": "AI assistant message",
  "chat.inputPlaceholder": "Ask about your data…",
  "chat.inputLabel": "Message for the AI assistant",
  "chat.send": "Send message",
  "chat.sending": "Sending message",
  "chat.disclaimer":
    "AI output may be wrong. Relationships are not causes, and health interpretations are not medical advice.",
  "chat.errorStatus": "Chat availability could not be checked.",
  "chat.errorLogin": "ChatGPT sign-in could not be started.",
  "chat.errorCopy": "The code could not be copied.",
  "chat.errorLoginRequired": "Connect your ChatGPT subscription before sending a message.",
  "chat.errorResponse": "The assistant could not complete this response.",
  "chat.errorStream": "The chat connection was interrupted.",
  // ── Workouts ────────────────────────────────────────────────────────────
  "workouts.title": "Workouts",
  "workouts.subtitle":
    "Every session, and everything the other connectors recorded while it was happening.",
  "workouts.loading": "Loading sessions…",
  "workouts.empty": "No sessions in this period.",
  "workouts.emptyHint":
    "Workouts arrive from Apple Health, WHOOP and Streak. A connector that has not run yet is not the same as a rest day.",
  "workouts.filterAll": "All",
  "workouts.filterWorkout": "Endurance",
  "workouts.filterStrength": "Strength",
  "workouts.range30": "Last 30 days",
  "workouts.range90": "Last 90 days",
  "workouts.range365": "Last year",
  "workouts.approximate": "Grouped by time and name",
  "workouts.approximateHint":
    "This session was imported before workouts carried an identifier, so its points are grouped by timestamp and title. Two sessions stamped alike can appear as one, and one session can appear as two.",
  "workouts.scanTruncated":
    "This period holds more rows than one scan reads. Narrow the range to see everything.",
  "workouts.weekOf": "Week of {date}",
  "workouts.moreMeasures": "+{count} more",
  "workouts.listTruncated":
    "Showing the newest {count} sessions in this period. Narrow the range to reach older ones.",
  "workouts.back": "All workouts",
  "workouts.exercises_one": "{count} exercise",
  "workouts.exercises_other": "{count} exercises",
  "workouts.sets_one": "{count} set",
  "workouts.sets_other": "{count} sets",
  "workouts.notFound": "That session is not in this workspace.",
  "workouts.clamped":
    "This session states an end more than 12 hours after its start, so the window shown is capped.",
  "workouts.measures": "What the session states",
  "workouts.derived": "Worked out from {fields}, not stated by the provider",
  "workouts.providerValue": "Provider stated {value} {unit}",
  "workouts.route": "Route",
  "workouts.routeMeasured": "Measured along the track: {distance}",
  "workouts.routeFixes_one": "{count} GPS fix",
  "workouts.routeFixes_other": "{count} GPS fixes",
  "workouts.routeFallback":
    "Drawn from the stored coordinates; these fixes predate the spatial column.",
  "workouts.streams": "During the session",
  "workouts.streamBucket": "One point per {seconds} s",
  "workouts.streamRange": "Range {min}–{max}",
  "workouts.streamTruncated": "Shortened to fit the chart.",
  "workouts.strength": "Sets",
  "workouts.strengthTruncated": "More sets than one response returns.",
  "workouts.topSet": "Best set",
  "workouts.totalVolume": "Volume",
  "workouts.totalReps": "Repetitions",
  "workouts.setNumber": "Set",
  "workouts.weight": "Weight",
  "workouts.reps": "Reps",
  "workouts.volume": "Volume",
  "workouts.surroundings": "Recorded at the same time",
  "workouts.surroundingsHint":
    "These connectors know nothing about the workout. They are here because their readings fall inside it.",
  "workouts.noStreams": "No second-by-second series for this session.",
  "workouts.noStrength": "No sets logged for this session.",

  // ── Muscle groups ───────────────────────────────────────────────────────
  "muscle.chest": "Chest",
  "muscle.back": "Back",
  "muscle.shoulders": "Shoulders",
  "muscle.biceps": "Biceps",
  "muscle.triceps": "Triceps",
  "muscle.forearms": "Forearms",
  "muscle.quads": "Quadriceps",
  "muscle.hamstrings": "Hamstrings",
  "muscle.glutes": "Glutes",
  "muscle.calves": "Calves",
  "muscle.core": "Core",
  "muscle.full_body": "Full body",
  "muscle.cardio": "Cardio",
  "muscle.other": "Other",

  // ── Strength progression ────────────────────────────────────────────────
  "analysis.tabStrength": "Strength",
  "analysis.strengthEmpty":
    "No resistance training in this period. Sets arrive from the Streak connector.",
  "analysis.strengthTruncated": "More sets than one analysis reads. The oldest are not included.",
  "analysis.strengthBalance": "Where the work went",
  "analysis.strengthBalanceHint":
    "Sets per muscle group. A share, not a total: what was pushed only means something beside what was pulled.",
  "analysis.strengthExercise": "Exercise",
  "analysis.strengthSessions": "Sessions",
  "analysis.strengthBest": "Best set",
  "analysis.strengthOneRm": "Estimated 1RM",
  "analysis.strengthDirection": "Direction",
  "analysis.strengthTooFew": "Fewer than {count} sessions — too few to call a direction.",
  "analysis.strengthBasis.estimated_1rm": "Measured as the estimated one-rep max",
  "analysis.strengthBasis.volume": "Measured as total volume",
  "analysis.strengthBasis.reps": "Measured as repetitions, this being a bodyweight exercise",
  "analysis.strengthBasis.none": "No basis",
  "analysis.direction.rising": "Rising",
  "analysis.direction.falling": "Falling",
  "analysis.direction.flat": "Flat",

  // ── Weekdays ────────────────────────────────────────────────────────────
  // The Analysis Service names the day; this is where it gets said. It used to
  // send the German word, so an English reader was shown "Montag" and there was
  // nothing the interface could do about it (rule 17).
  "weekday.monday": "Monday",
  "weekday.tuesday": "Tuesday",
  "weekday.wednesday": "Wednesday",
  "weekday.thursday": "Thursday",
  "weekday.friday": "Friday",
  "weekday.saturday": "Saturday",
  "weekday.sunday": "Sunday",

  // Reached by Tab before anything else; invisible until then.
  "nav.skipToContent": "Skip to content",

  // --- end of catalogue ---
} satisfies Record<string, string>;

export type MessageKey = keyof typeof en;
