# Datenqualität

Das Data Quality Center zeigt, ob Daten vollständig, widerspruchsfrei und für Analysen geeignet sind.

## Kennzahlen

| Kennzahl | Bedeutung | Empfehlung |
| --- | --- | --- |
| Datenlücken | Tage ohne Messwert pro Metrik im 30-Tage-Fenster | Connector prüfen, Token erneuern oder Sync erneut starten. |
| Quellenkonflikte | Messwerte gleicher Metrik weichen zwischen Quellen deutlich ab | Primärquelle festlegen oder Maßeinheiten prüfen. |

## Interpretation

- **0 Lücken**: Daten sind für einfache Trends und Korrelationen gut geeignet.
- **1-3 Lücken**: Analyse ist meistens nutzbar, aber Ausreißer sollten vorsichtig interpretiert werden.
- **Mehrere Lücken**: Empfehlungen können verzerrt sein; zuerst Datenquelle reparieren.
