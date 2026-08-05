import React from "react";
import Link from "next/link";
import { Shield, Lock, Eye, Key, Flame, MapPin, Activity, ArrowLeft, CheckCircle2 } from "lucide-react";

export const metadata = {
  title: "Datenschutzerklärung — Quantified Self Platform",
  description: "Öffentliche Datenschutzerklärung und Informationen zur DSGVO-konformen Verarbeitung deiner Gesundheits-, GPS- und Fitnesstracking-Daten.",
};

export default function PrivacyPolicyPage() {
  return (
    <div className="min-h-screen bg-slate-100 text-slate-900 flex flex-col font-sans selection:bg-emerald-100 selection:text-[#0d5c3a]">
      {/* Top Navbar Header */}
      <header className="border-b border-slate-200/80 bg-white/85 backdrop-blur-md sticky top-0 z-50">
        <div className="max-w-6xl mx-auto px-6 h-16 flex items-center justify-between">
          <Link href="/" className="flex items-center gap-2 text-slate-600 hover:text-slate-900 transition-colors text-sm font-semibold">
            <ArrowLeft className="w-4 h-4 text-[#0d5c3a]" />
            <span>Zurück zur Plattform</span>
          </Link>
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 rounded-xl bg-emerald-50 border border-emerald-100 flex items-center justify-center">
              <Shield className="w-4 h-4 text-[#0d5c3a]" />
            </div>
            <span className="font-extrabold text-sm tracking-wide text-slate-900">Quantified Self</span>
          </div>
        </div>
      </header>

      {/* Main Content Area */}
      <main className="flex-1 max-w-5xl mx-auto px-6 py-12 space-y-10 w-full">
        {/* Title Banner */}
        <div className="space-y-4 border-b border-slate-200 pb-8">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-emerald-50 border border-emerald-100 text-[#0d5c3a] text-xs font-semibold">
            <CheckCircle2 className="w-3.5 h-3.5" />
            <span>Öffentlich zugänglich & DSGVO-Konform</span>
          </div>
          <h1 className="text-4xl font-extrabold tracking-tight text-slate-900 sm:text-5xl">
            Datenschutzerklärung
          </h1>
          <p className="text-slate-600 text-sm leading-relaxed max-w-2xl">
            Informationen zur Erhebung, Verarbeitung und zum Schutz deiner persönlichen Gesundheits-, 
            Ernährungs- und Standortdaten auf der Quantified Self Plattform.
          </p>
          <div className="text-xs text-slate-500 font-mono">
            Stand: 3. August 2026 • Version 2.0
          </div>
        </div>

        {/* Core Principles Grid */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div className="p-5 rounded-3xl bg-white border border-slate-200 space-y-2 shadow-sm">
            <div className="w-9 h-9 rounded-xl bg-emerald-50 flex items-center justify-center text-[#0d5c3a]">
              <Lock className="w-5 h-5" />
            </div>
            <h3 className="text-sm font-bold text-slate-900">Fernet AES-256</h3>
            <p className="text-xs text-slate-500 leading-relaxed">
              Alle API-Tokens, Secrets und OAuth-Zugänge werden verschlüsselt in PostgreSQL gespeichert.
            </p>
          </div>

          <div className="p-5 rounded-3xl bg-white border border-slate-200 space-y-2 shadow-sm">
            <div className="w-9 h-9 rounded-xl bg-emerald-50 flex items-center justify-center text-[#0d5c3a]">
              <Shield className="w-5 h-5" />
            </div>
            <h3 className="text-sm font-bold text-slate-900">Mandantentrennung</h3>
            <p className="text-xs text-slate-500 leading-relaxed">
              Strikte Abfassung auf Datenbank-Ebene durch isolierte Workspace-IDs (<code className="text-[#0d5c3a]">tenant_id</code>).
            </p>
          </div>

          <div className="p-5 rounded-3xl bg-white border border-slate-200 space-y-2 shadow-sm">
            <div className="w-9 h-9 rounded-xl bg-emerald-50 flex items-center justify-center text-[#0d5c3a]">
              <Eye className="w-5 h-5" />
            </div>
            <h3 className="text-sm font-bold text-slate-900">Kein Datenverkauf</h3>
            <p className="text-xs text-slate-500 leading-relaxed">
              Deine Daten werden niemals an Werbenetzwerke weitergegeben, analysiert oder verkauft.
            </p>
          </div>
        </div>

        {/* Section 1: Verantwortlicher */}
        <section className="space-y-3">
          <h2 className="text-xl font-bold text-slate-900 flex items-center gap-2">
            <span>1. Verantwortlicher & Geltungsbereich</span>
          </h2>
          <p className="text-slate-600 text-sm leading-relaxed">
            Verantwortlich im Sinne der Datenschutz-Grundverordnung (DSGVO) und anderer nationaler Datenschutzgesetze ist der Betreiber der 
            <strong className="text-slate-900"> Quantified Self Platform</strong>. Diese Erklärung gilt für die Nutzung aller Funktionen der Plattform, 
            einschließlich der Anbindung externer Drittanbieter-Dienste.
          </p>
        </section>

        {/* Section 2: Datenquellen & Importer */}
        <section className="space-y-4">
          <h2 className="text-xl font-bold text-slate-900">
            2. Verarbeitete Datenquellen & Integrationen
          </h2>
          <p className="text-slate-600 text-sm leading-relaxed">
            Nach deiner ausdrücklichen Verknüpfung und Autorisierung in den Systemeinstellungen importiert und verarbeitet Quantified Self folgende Datenquellen:
          </p>

          <div className="space-y-3">
            {/* WHOOP */}
            <div className="p-4 rounded-3xl bg-white border border-slate-200 flex items-start gap-3.5 shadow-sm">
              <div className="p-2.5 rounded-xl bg-emerald-50 text-[#0d5c3a] mt-0.5">
                <Activity className="w-5 h-5" />
              </div>
              <div className="space-y-1">
                <h3 className="text-sm font-bold text-slate-900">WHOOP (Fitness & Recovery)</h3>
                <p className="text-xs text-slate-500 leading-relaxed">
                  Verarbeitung von WHOOP Profil- und Biometriedaten, Herzfrequenzvariabilität (HRV), Schlafphasen (REM, Deep, Light), 
                  Strain Score, Recovery Score, SpO2 und Workout-Intensitäten via der offiziellen WHOOP Developer API v2.
                </p>
              </div>
            </div>

            {/* Yazio */}
            <div className="p-4 rounded-3xl bg-white border border-slate-200 flex items-start gap-3.5 shadow-sm">
              <div className="p-2.5 rounded-xl bg-emerald-50 text-[#0d5c3a] mt-0.5">
                <Flame className="w-5 h-5" />
              </div>
              <div className="space-y-1">
                <h3 className="text-sm font-bold text-slate-900">Yazio (Ernährung & Tagebuch)</h3>
                <p className="text-xs text-slate-500 leading-relaxed">
                  Import von konsumierten Lebensmitteln, Mahlzeiten-Zeitstempeln, Kalorien, Wasseraufnahme und Makronährstoffverhältnissen (Proteine, Kohlenhydrate, Fette).
                </p>
              </div>
            </div>

            {/* Dawarich */}
            <div className="p-4 rounded-3xl bg-white border border-slate-200 flex items-start gap-3.5 shadow-sm">
              <div className="p-2.5 rounded-xl bg-emerald-50 text-[#0d5c3a] mt-0.5">
                <MapPin className="w-5 h-5" />
              </div>
              <div className="space-y-1">
                <h3 className="text-sm font-bold text-slate-900">Dawarich (GPS & Standorte)</h3>
                <p className="text-xs text-slate-500 leading-relaxed">
                  Verarbeitung von WGS84 GPS-Koordinaten (Breitengrad, Längengrad, Höhe, Geschwindigkeit) zur kartografischen Darstellung und Bewegungsmuster-Analyse über PostGIS Spatial Indexing.
                </p>
              </div>
            </div>
          </div>
        </section>

        {/* Section 3: Rechtsgrundlagen & Rechte */}
        <section className="space-y-3">
          <h2 className="text-xl font-bold text-slate-900">
            3. Rechtsgrundlagen (Art. 6 & Art. 9 DSGVO)
          </h2>
          <p className="text-slate-600 text-sm leading-relaxed">
            Die Verarbeitung von allgemeinen Profil- und Trackingdaten erfolgt auf Grundlage deiner Einwilligung (Art. 6 Abs. 1 lit. a DSGVO) 
            sowie zur Vertragserfüllung (Art. 6 Abs. 1 lit. b DSGVO). 
            Soweit verarbeitete Metriken Gesundheitsdaten darstellen, erfolgt die Verarbeitung auf Basis deiner ausdrücklichen Einwilligung gemäß 
            <strong className="text-slate-900"> Art. 9 Abs. 2 lit. a DSGVO</strong>.
          </p>
        </section>

        {/* Section 4: Rechte & Wiederruf */}
        <section className="space-y-3">
          <h2 className="text-xl font-bold text-slate-900">
            4. Deine Rechte & Widerrufsrecht
          </h2>
          <ul className="space-y-2 text-slate-600 text-sm list-disc pl-5 leading-relaxed marker:text-emerald-700">
            <li><strong className="text-slate-900">Widerrufsrecht (Art. 7 Abs. 3 DSGVO):</strong> Du kannst jede Connector-Verknüpfung jederzeit mit 1 Klick im Dashboard unter <em>Connectoren</em> entfernen oder in den Einstellungen des jeweiligen Drittanbieters (z. B. WHOOP) widerrufen.</li>
            <li><strong className="text-slate-900">Recht auf Löschung (Art. 17 DSGVO):</strong> Alle mit deinem Account verknüpften Datenpunkte und API-Tokens werden bei Account-Löschung oder Entfernung der Datenquelle unverzüglich aus der Datenbank entfernt.</li>
            <li><strong className="text-slate-900">Recht auf Auskunft (Art. 15 DSGVO):</strong> Du kannst im <em>Universal Data Explorer</em> jederzeit alle über dich gespeicherten Rohdaten und Metriken einsehen und exportieren.</li>
          </ul>
        </section>

        {/* Section 5: Kontaktaufnahme */}
        <section className="p-6 rounded-3xl bg-[#0d5c3a] border border-[#0d5c3a] space-y-2 shadow-lg shadow-emerald-900/10">
          <h2 className="text-base font-bold text-white">Datenschutzanfragen & Kontakt</h2>
          <p className="text-xs text-emerald-50 leading-relaxed">
            Für Fragen zum Datenschutz, Auskunfts- oder Löschanträge wende dich direkt an den Systemadministrator oder nutze die Schaltflächen in den Kontoeinstellungen deines Dashboard-Workspaces.
          </p>
        </section>
      </main>

      {/* Footer */}
      <footer className="border-t border-slate-200 py-8 bg-white/70 text-center text-xs text-slate-500">
        <div className="max-w-4xl mx-auto px-6 space-y-2">
          <p>© {new Date().getFullYear()} Quantified Self Platform. Alle Rechte vorbehalten.</p>
          <div className="flex justify-center gap-4 text-slate-500">
            <Link href="/" className="hover:text-slate-900 transition-colors">Dashboard</Link>
            <span>•</span>
            <Link href="/privacy" className="text-[#0d5c3a] hover:text-[#08432a] font-semibold">Datenschutz</Link>
          </div>
        </div>
      </footer>
    </div>
  );
}
