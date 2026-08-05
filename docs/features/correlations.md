# Korrelationen & einfache Analysen

Die Korrelationen-Ansicht bewertet, welche Metriken sich gemeinsam verändern. Der aktuelle Ansatz ist ressourcenschonend und deterministisch.

## Einordnung des Pearson-Koeffizienten

| Absolutwert | Stärke | Interpretation |
| --- | --- | --- |
| `0.00–0.19` | sehr niedrig | Praktisch kein linearer Zusammenhang. |
| `0.20–0.39` | niedrig | Schwaches Muster; mehr Daten sammeln. |
| `0.40–0.59` | moderat | Beobachtbarer Zusammenhang, Hypothese prüfen. |
| `0.60–0.79` | stark | Relevantes Muster, aber keine Kausalität. |
| `0.80–1.00` | sehr stark | Sehr deutlicher gemeinsamer Verlauf; Datenqualität prüfen. |

## Günstige nächste ML-Algorithmen

- Spearman-Korrelation für monotone, nicht-lineare Zusammenhänge.
- Rolling Correlation für zeitabhängige Muster.
- Isolation Forest oder robustes Z-Score-Scoring für Ausreißer.
- Kleine Random-Forest-Regressoren pro Zielmetrik, um Feature-Wichtigkeiten zu schätzen.

Alle Verfahren sollten tenant-scoped über Core/gRPC lesen und keine direkte Datenbankverbindung im Analysis Service nutzen.
