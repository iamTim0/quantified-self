import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Impressum — Quantified Self",
  description: "Anbieterkennzeichnung nach § 5 DDG und § 18 Abs. 2 MStV.",
  robots: { index: false, follow: false },
};

/** Marks a value the operator must supply before going live. */
function Platzhalter({ children }: { children: React.ReactNode }) {
  return <span className="placeholder">[{children}]</span>;
}

export default function ImpressumPage() {
  return (
    <article>
      <h1>Impressum</h1>
      <p>Angaben gemäß § 5 Digitale-Dienste-Gesetz (DDG).</p>

      <h2>Anbieter</h2>
      <p>
        <Platzhalter>Vollständiger Name bzw. Firma inkl. Rechtsform</Platzhalter>
        <br />
        <Platzhalter>Straße und Hausnummer</Platzhalter>
        <br />
        <Platzhalter>PLZ und Ort</Platzhalter>
        <br />
        <Platzhalter>Land</Platzhalter>
      </p>

      <h2>Vertreten durch</h2>
      <p>
        <Platzhalter>
          Name der vertretungsberechtigten Person(en); bei juristischen Personen alle
          Geschäftsführer bzw. Vorstandsmitglieder
        </Platzhalter>
      </p>

      <h2>Kontakt</h2>
      <p>
        E-Mail: <Platzhalter>kontakt@example.org</Platzhalter>
        <br />
        Telefon: <Platzhalter>Telefonnummer</Platzhalter>
      </p>
      <p>
        Eine Telefonnummer ist nicht zwingend erforderlich, es muss aber ein zweiter,
        unmittelbarer Kommunikationsweg neben der E-Mail-Adresse bestehen (z. B.
        Kontaktformular mit zugesicherter Reaktionszeit).
      </p>

      <h2>Registereintrag</h2>
      <p>
        Registergericht: <Platzhalter>z. B. Amtsgericht Musterstadt</Platzhalter>
        <br />
        Registernummer: <Platzhalter>z. B. HRB 12345</Platzhalter>
      </p>
      <p>
        Entfällt bei Privatpersonen und nicht eingetragenen Einzelunternehmen. Diesen
        Abschnitt dann bitte vollständig löschen statt leer zu lassen.
      </p>

      <h2>Umsatzsteuer-Identifikationsnummer</h2>
      <p>
        Umsatzsteuer-Identifikationsnummer gemäß § 27 a Umsatzsteuergesetz:{" "}
        <Platzhalter>DE000000000</Platzhalter>
      </p>
      <p>
        Bei Anwendung der Kleinunternehmerregelung (§ 19 UStG) besteht in der Regel keine
        USt-IdNr.; dieser Abschnitt entfällt dann.
      </p>

      <h2>Aufsichtsbehörde</h2>
      <p>
        <Platzhalter>
          Nur erforderlich bei zulassungspflichtigen Tätigkeiten — zuständige
          Aufsichtsbehörde mit Anschrift
        </Platzhalter>
      </p>

      <h2>Berufsrechtliche Angaben</h2>
      <p>
        <Platzhalter>
          Nur bei reglementierten Berufen — gesetzliche Berufsbezeichnung, Staat der
          Verleihung, zuständige Kammer und maßgebliche berufsrechtliche Regelungen
        </Platzhalter>
      </p>

      <h2>Verantwortlich für den Inhalt nach § 18 Abs. 2 MStV</h2>
      <p>
        <Platzhalter>Name</Platzhalter>
        <br />
        <Platzhalter>Anschrift, sofern abweichend von oben</Platzhalter>
      </p>

      <h2>Streitbeilegung</h2>
      <p>
        Die Europäische Kommission stellt eine Plattform zur Online-Streitbeilegung
        bereit:{" "}
        <a href="https://ec.europa.eu/consumers/odr/" rel="noreferrer noopener" target="_blank">
          https://ec.europa.eu/consumers/odr/
        </a>
        .
      </p>
      <p>
        <Platzhalter>
          Angabe ergänzen, ob eine Teilnahme an einem Streitbeilegungsverfahren vor einer
          Verbraucherschlichtungsstelle erfolgt — die Angabe ist verpflichtend, auch wenn
          keine Teilnahme erfolgt
        </Platzhalter>
      </p>

      <h2>Haftung für Inhalte und Links</h2>
      <p>
        Als Diensteanbieter sind wir für eigene Inhalte auf diesen Seiten nach den
        allgemeinen Gesetzen verantwortlich. Wir sind jedoch nicht verpflichtet,
        übermittelte oder gespeicherte fremde Informationen zu überwachen oder nach
        Umständen zu forschen, die auf eine rechtswidrige Tätigkeit hinweisen.
      </p>
      <p>
        Diese Anwendung ruft auf ausdrückliche Veranlassung der Nutzerinnen und Nutzer
        Daten von externen Diensten ab (siehe Datenschutzerklärung). Für die Inhalte
        dieser externen Dienste ist ausschließlich deren jeweiliger Anbieter
        verantwortlich.
      </p>

      <h2>Hinweis zur Vorlage</h2>
      <p>
        Dieses Impressum ist eine Vorlage. Welche Angaben im Einzelfall erforderlich sind,
        hängt von Rechtsform, Tätigkeit und Zielmarkt ab. Bitte vor Veröffentlichung durch
        eine qualifizierte Stelle prüfen lassen und alle gelb markierten Platzhalter
        ersetzen oder die betreffenden Abschnitte entfernen.
      </p>

      <p>
        Stand: <Platzhalter>Datum der letzten Aktualisierung</Platzhalter>
      </p>
    </article>
  );
}
