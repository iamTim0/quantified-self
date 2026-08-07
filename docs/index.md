# Quantified Self Dokumentation

Diese Dokumentation ist als separate, statische Website für Betrieb und Anwenderhilfe gedacht. Wir nutzen **Material for MkDocs**, weil es Markdown als Pflegeformat, Suche, Navigation und ein schlankes Python-basiertes Build-System kombiniert. MkDocs beschreibt sich selbst als statischen Generator für Projektdokumentation aus Markdown-Dateien, Material for MkDocs ergänzt eine professionelle, durchsuchbare Oberfläche.

## Lokaler Betrieb

```bash
task docs:serve
```

Im Docker-Setup wird die Dokumentation über Traefik unter `/docs` geroutet und bleibt damit bewusst von der Produkt-UI getrennt.

## Architekturprinzipien

- Importer sind stateless und veröffentlichen ausschließlich tenant-scoped NATS-Events auf `qs.ingest.<source_type>`.
- Credentials werden dynamisch aus Core geladen und nicht im Importer gespeichert.
- Jedes Event enthält `tenant_id`, `source_id`, `metric_type`, `timestamp` und einen deterministischen `idempotency_key`.
- Core bleibt der einzige Service mit Datenbankzugriff.

## Rechtliches

Die Rechtstexte werden in der Anwendung selbst gepflegt, damit sie immer zur laufenden
Version passen:

- [Datenschutzerklärung](/legal/datenschutz)
- [Impressum](/legal/impressum)

Beide sind Vorlagen mit Platzhaltern und müssen vor einem produktiven Einsatz durch eine
qualifizierte Stelle geprüft werden.

## Externe Referenzen

- [MkDocs](https://www.mkdocs.org/) für Markdown-basierte Projektdokumentation.
- [Material for MkDocs](https://squidfunk.github.io/mkdocs-material/) für Suche, Navigation und responsives Design.
