import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Datenschutzerklärung — Quantified Self",
  description:
    "Informationen zur Verarbeitung personenbezogener Daten in der Quantified-Self-Plattform.",
  robots: { index: false, follow: false },
};

/** Marks a value the operator must supply before going live. */
function Platzhalter({ children }: { children: React.ReactNode }) {
  return <span className="placeholder">[{children}]</span>;
}

export default function DatenschutzPage() {
  return (
    <article>
      <h1>Datenschutzerklärung</h1>
      <p>
        Diese Erklärung beschreibt, welche personenbezogenen Daten in dieser
        Quantified-Self-Plattform verarbeitet werden, zu welchem Zweck und auf welcher
        Rechtsgrundlage. Sie beschreibt den tatsächlichen Stand der Anwendung.
      </p>

      <h2>1. Verantwortlicher</h2>
      <p>
        <Platzhalter>Name bzw. Firma</Platzhalter>
        <br />
        <Platzhalter>Anschrift</Platzhalter>
        <br />
        E-Mail: <Platzhalter>datenschutz@example.org</Platzhalter>
      </p>
      <p>
        Datenschutzbeauftragte Person:{" "}
        <Platzhalter>
          Name und Kontakt, sofern eine Benennungspflicht nach Art. 37 DSGVO besteht —
          sonst diesen Absatz entfernen
        </Platzhalter>
      </p>

      <h2>2. Besondere Kategorien personenbezogener Daten</h2>
      <p>
        Diese Anwendung verarbeitet <strong>Gesundheitsdaten</strong> (z. B. Schlaf,
        Herzfrequenzvariabilität, Erholung, Training, Ernährung) sowie{" "}
        <strong>Standortdaten</strong>. Gesundheitsdaten sind besondere Kategorien
        personenbezogener Daten im Sinne von Art. 9 Abs. 1 DSGVO.
      </p>
      <p>
        Ihre Verarbeitung erfolgt ausschließlich auf Grundlage Ihrer ausdrücklichen
        Einwilligung nach Art. 9 Abs. 2 lit. a DSGVO. Sie erteilen diese Einwilligung,
        indem Sie einen Connector einrichten oder Daten selbst hochladen. Sie können sie
        jederzeit mit Wirkung für die Zukunft widerrufen, indem Sie den Connector
        entfernen oder Ihr Konto löschen.
      </p>

      <h2>3. Konto und Arbeitsbereich</h2>
      <p>Bei der Registrierung werden verarbeitet:</p>
      <ul>
        <li>E-Mail-Adresse (dient als Anmeldename)</li>
        <li>Anzeigename</li>
        <li>Passwort — ausschließlich als bcrypt-Hash gespeichert, niemals im Klartext</li>
        <li>Rolle innerhalb des Arbeitsbereichs (owner, admin, member)</li>
        <li>Zeitpunkt der Kontoerstellung</li>
      </ul>
      <p>
        Jedes Konto gehört zu genau einem Arbeitsbereich (&bdquo;Tenant&ldquo;). Sämtliche
        Datenbankabfragen sind auf diesen Arbeitsbereich eingeschränkt; ein Zugriff auf
        Daten anderer Arbeitsbereiche ist technisch ausgeschlossen, sofern nicht über die
        Freigabefunktion ausdrücklich eine Freigabe erteilt wurde.
      </p>
      <p>
        Rechtsgrundlage: Art. 6 Abs. 1 lit. b DSGVO (Erfüllung des Nutzungsvertrags).
      </p>

      <h2>4. Anmeldung, Sitzungen und Cookies</h2>
      <p>
        Für die Anmeldung setzt diese Anwendung technisch notwendige Cookies. Es werden
        keine Cookies zu Werbe-, Tracking- oder Analysezwecken verwendet und keine Daten
        an Dritte weitergegeben. Gesetzt werden:
      </p>
      <table>
        <thead>
          <tr>
            <th>Name</th>
            <th>Inhalt</th>
            <th>Eigenschaften</th>
            <th>Speicherdauer</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>
              <code>qs_access</code>
            </td>
            <td>Signiertes Zugriffstoken (JWT) mit Nutzer-, Tenant- und Rollenangabe</td>
            <td>HttpOnly, Secure, SameSite=Lax</td>
            <td>12 Stunden</td>
          </tr>
          <tr>
            <td>
              <code>qs_refresh</code>
            </td>
            <td>Zufälliges Erneuerungstoken; serverseitig nur als Hash gespeichert</td>
            <td>HttpOnly, Secure, SameSite=Lax, nur an Anmelde-Endpunkte</td>
            <td>30 Tage</td>
          </tr>
          <tr>
            <td>
              <code>qs_csrf</code>
            </td>
            <td>
              Zufallswert zum Schutz vor Cross-Site-Request-Forgery. Kein Zugangstoken:
              er erlaubt für sich genommen keinen Zugriff auf Daten.
            </td>
            <td>Secure, SameSite=Lax, für die Oberfläche lesbar</td>
            <td>30 Tage</td>
          </tr>
        </tbody>
      </table>
      <p>
        <code>HttpOnly</code> bedeutet, dass die beiden Zugangs-Cookies für JavaScript im
        Browser nicht lesbar sind. Sie können damit auch bei einer Sicherheitslücke in der
        Oberfläche nicht ausgelesen und an Dritte übertragen werden.
      </p>
      <p>
        Diese Cookies sind für den Betrieb des von Ihnen ausdrücklich angeforderten
        Dienstes unbedingt erforderlich (§ 25 Abs. 2 Nr. 2 TDDDG) und bedürfen daher keiner
        gesonderten Einwilligung. Beim Abmelden werden alle genannten Cookies gelöscht und
        die zugehörige Sitzung zusätzlich serverseitig ungültig gemacht.
      </p>
      <p>
        Zusätzlich wird beim Anmelden über einen externen Anbieter kurzzeitig der Name des
        gewählten Anbieters im <code>sessionStorage</code> des Browsers abgelegt, damit die
        Rückleitung dem richtigen Anbieter zugeordnet werden kann. Dieser Eintrag enthält
        keine personenbezogenen Daten und wird nach Abschluss der Anmeldung entfernt.
      </p>
      <p>
        Ein Erneuerungstoken ist nur einmal verwendbar. Wird ein bereits verbrauchtes
        Token erneut vorgelegt, werden vorsorglich sämtliche Sitzungen des Kontos beendet.
      </p>

      <h2>5. Daten aus verbundenen Diensten</h2>
      <p>
        Sie entscheiden selbst, welche Connectoren Sie einrichten. Ohne Einrichtung werden
        keine Daten von Dritten abgerufen. Je nach Auswahl werden verarbeitet:
      </p>
      <table>
        <thead>
          <tr>
            <th>Connector</th>
            <th>Datenarten</th>
            <th>Abruf</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>WHOOP</td>
            <td>Erholung, Schlaf, Belastung, Workouts</td>
            <td>Abruf durch die Plattform</td>
          </tr>
          <tr>
            <td>Yazio</td>
            <td>Ernährungstagebuch, Kalorien, Makronährstoffe</td>
            <td>Abruf durch die Plattform</td>
          </tr>
          <tr>
            <td>Dawarich</td>
            <td>GPS-Standortpunkte und Bewegungsverläufe</td>
            <td>Abruf durch die Plattform</td>
          </tr>
          <tr>
            <td>Kalender (ICS)</td>
            <td>Termine, Titel, Dauer, belegte Zeit</td>
            <td>Abruf durch die Plattform</td>
          </tr>
          <tr>
            <td>Home Assistant, Wetter</td>
            <td>Sensor- und Umgebungswerte</td>
            <td>Abruf durch die Plattform</td>
          </tr>
          <tr>
            <td>Apple Health</td>
            <td>Aktivität, Vitalwerte, Schlaf, Workouts</td>
            <td>Übermittlung durch Ihr Gerät</td>
          </tr>
          <tr>
            <td>Streak</td>
            <td>Krafttraining, Sätze, Wiederholungen, Gewichte</td>
            <td>Übermittlung durch Ihre App</td>
          </tr>
        </tbody>
      </table>
      <p>
        Rechtsgrundlage: Art. 6 Abs. 1 lit. a und Art. 9 Abs. 2 lit. a DSGVO
        (Einwilligung), erteilt durch die Einrichtung des jeweiligen Connectors.
      </p>
      <p>
        Beim Abruf werden Ihre Daten von den jeweiligen Anbietern an die Plattform
        übermittelt. Für deren eigene Verarbeitung gelten die Datenschutzhinweise des
        jeweiligen Anbieters. Prüfen Sie insbesondere, ob dabei eine Übermittlung in
        Drittländer stattfindet.
      </p>

      <h2>6. Zugangsdaten zu verbundenen Diensten</h2>
      <p>
        Zugangstoken und API-Schlüssel, die Sie für Connectoren hinterlegen, werden
        symmetrisch verschlüsselt gespeichert (Fernet, AES-256). In der Oberfläche und in
        allen API-Antworten erscheinen sie ausschließlich maskiert. Sie werden nicht
        protokolliert und nicht im Klartext über den Nachrichtenbus übertragen.
      </p>
      <p>
        Von der Plattform erzeugte API-Schlüssel für eingehende Daten werden{" "}
        <strong>ausschließlich als Hashwert</strong> gespeichert. Der vollständige
        Schlüssel wird genau einmal bei der Erstellung angezeigt und ist danach technisch
        nicht mehr abrufbar.
      </p>
      <p>
        Die URL eines privaten Kalender-Feeds ist selbst ein Zugangsgeheimnis. Sie wird
        daher wie ein Zugangsdatum behandelt und niemals vollständig protokolliert.
      </p>

      <h2>7. Mess-, Analyse- und Qualitätsdaten</h2>
      <p>
        Importierte Messwerte werden mit Zeitstempel, Metrikart, Quelle, Wert und
        Metadaten gespeichert. Daraus werden auf Ihren Wunsch statistische Auswertungen
        berechnet, insbesondere Korrelationen zwischen Metriken, Trends sowie Angaben zu
        Datenlücken und Quellenkonflikten.
      </p>
      <p>
        Diese Auswertungen sind rein statistisch. Sie beschreiben Zusammenhänge, nicht
        Ursachen, und stellen <strong>keine medizinische Diagnose, Beratung oder
        Behandlungsempfehlung</strong> dar. Es findet keine automatisierte
        Entscheidungsfindung im Sinne von Art. 22 DSGVO statt.
      </p>
      <p>
        Zusätzlich wird protokolliert, wann welcher Import mit welchem Zeitfenster
        ausgeführt wurde und wie viele Datenpunkte dabei neu waren. Dieses Importprotokoll
        dient der Nachvollziehbarkeit und der Vermeidung von Datenlücken.
      </p>

      <h2>8. Protokolldaten und Betrieb</h2>
      <p>
        Zur Fehlersuche und Betriebssicherheit werden technische Protokolle erzeugt. Sie
        enthalten Zeitpunkt, angefragten Endpunkt, HTTP-Statuscode, Dauer, die Kennung des
        Arbeitsbereichs sowie eine zufällige Anfragekennung (<code>X-Request-ID</code>),
        über die eine Anfrage dienstübergreifend nachvollzogen werden kann.
      </p>
      <p>
        Zugangsdaten, Token und API-Schlüssel werden nicht protokolliert. Der Webserver
        bzw. die Hosting-Infrastruktur kann darüber hinaus Zugriffsprotokolle inklusive
        IP-Adresse führen.
      </p>
      <p>
        Rechtsgrundlage: Art. 6 Abs. 1 lit. f DSGVO (berechtigtes Interesse an einem
        sicheren und funktionsfähigen Betrieb).
      </p>
      <p>
        Aufbewahrungsdauer der Protokolle:{" "}
        <Platzhalter>tatsächliche Aufbewahrungsdauer eintragen, z. B. 14 Tage</Platzhalter>
      </p>

      <h2>9. Hosting und Auftragsverarbeitung</h2>
      <p>
        Die Anwendung wird betrieben bei:{" "}
        <Platzhalter>Name und Anschrift des Hosting-Anbieters, Serverstandort</Platzhalter>
      </p>
      <p>
        Mit dem Anbieter besteht ein Vertrag zur Auftragsverarbeitung nach Art. 28 DSGVO.
        Sofern eine Verarbeitung außerhalb der EU/des EWR stattfindet, ist hier die
        Grundlage der Übermittlung anzugeben:{" "}
        <Platzhalter>
          z. B. Standardvertragsklauseln oder Angemessenheitsbeschluss
        </Platzhalter>
        .
      </p>
      <p>
        Weitere eingesetzte Auftragsverarbeiter:{" "}
        <Platzhalter>
          auflisten, z. B. Monitoring, Backup oder E-Mail-Versand — oder Abschnitt
          entfernen, wenn keine bestehen
        </Platzhalter>
      </p>

      <h2>10. Externe Anmeldedienste</h2>
      <p>
        Derzeit werden <strong>keine</strong> externen Anmeldedienste (etwa Google-Login
        oder andere OIDC-Anbieter) verwendet. Die Anmeldung erfolgt ausschließlich mit
        E-Mail-Adresse und Passwort.
      </p>
      <p>
        Sollte ein solcher Anbieter künftig eingebunden werden, ist dieser Abschnitt vor
        der Aktivierung um Anbieter, übermittelte Daten, Zweck und Rechtsgrundlage zu
        ergänzen.
      </p>

      <h2>11. Weitergabe an Dritte</h2>
      <p>
        Eine Weitergabe Ihrer Daten findet nicht statt, mit folgenden Ausnahmen:
      </p>
      <ul>
        <li>
          an von Ihnen selbst eingerichtete Connectoren, soweit für den Abruf erforderlich;
        </li>
        <li>an Auftragsverarbeiter nach Abschnitt 9;</li>
        <li>
          an andere Arbeitsbereiche, wenn Sie über die Freigabefunktion ausdrücklich eine
          Freigabe erteilen — diese können Sie jederzeit widerrufen;
        </li>
        <li>soweit eine gesetzliche Verpflichtung besteht.</li>
      </ul>
      <p>Ein Verkauf von Daten oder eine Nutzung für Werbung findet nicht statt.</p>

      <h2>12. Speicherdauer</h2>
      <ul>
        <li>
          Konto- und Messdaten: bis zur Löschung durch Sie oder bis zur Löschung des Kontos.
        </li>
        <li>Erneuerungstoken: 30 Tage, bei Abmeldung sofort ungültig.</li>
        <li>
          Sperrliste abgemeldeter Zugriffstoken: bis zum ohnehin eintretenden Ablauf des
          Tokens; danach automatische Bereinigung.
        </li>
        <li>
          Technische Protokolle:{" "}
          <Platzhalter>Aufbewahrungsdauer wie in Abschnitt 8</Platzhalter>.
        </li>
      </ul>

      <h2>13. Ihre Rechte</h2>
      <p>Sie haben nach der DSGVO folgende Rechte:</p>
      <ul>
        <li>Auskunft über die verarbeiteten Daten (Art. 15)</li>
        <li>Berichtigung unrichtiger Daten (Art. 16)</li>
        <li>Löschung (Art. 17)</li>
        <li>Einschränkung der Verarbeitung (Art. 18)</li>
        <li>Datenübertragbarkeit (Art. 20)</li>
        <li>Widerspruch gegen Verarbeitungen auf Grundlage berechtigter Interessen (Art. 21)</li>
        <li>
          Widerruf erteilter Einwilligungen mit Wirkung für die Zukunft (Art. 7 Abs. 3)
        </li>
      </ul>
      <p>Innerhalb der Anwendung können Sie unmittelbar:</p>
      <ul>
        <li>einzelne Connectoren samt gespeicherter Zugangsdaten entfernen,</li>
        <li>API-Schlüssel widerrufen,</li>
        <li>sämtliche importierten Messdaten löschen,</li>
        <li>Ihr Konto vollständig löschen.</li>
      </ul>
      <p>
        Sie haben außerdem das Recht, sich bei einer Datenschutz-Aufsichtsbehörde zu
        beschweren, insbesondere in dem Mitgliedstaat Ihres Aufenthaltsorts oder des
        mutmaßlichen Verstoßes. Zuständige Behörde für den Verantwortlichen:{" "}
        <Platzhalter>zuständige Aufsichtsbehörde mit Anschrift</Platzhalter>
      </p>

      <h2>14. Datensicherheit</h2>
      <ul>
        <li>Übertragung ausschließlich über TLS.</li>
        <li>Passwörter als bcrypt-Hash, API-Schlüssel als SHA-256-Hash gespeichert.</li>
        <li>Connector-Zugangsdaten mit Fernet (AES-256) verschlüsselt.</li>
        <li>
          Jede Anfrage wird serverseitig authentifiziert; die Zuordnung zum Arbeitsbereich
          wird ausschließlich aus dem geprüften Token abgeleitet und nicht aus frei
          setzbaren Kopfzeilen.
        </li>
        <li>Interne Schnittstellen sind von außen nicht erreichbar.</li>
      </ul>

      <h2>15. Änderungen dieser Erklärung</h2>
      <p>
        Diese Erklärung wird angepasst, wenn sich die Verarbeitung ändert. Maßgeblich ist
        die jeweils hier veröffentlichte Fassung.
      </p>
      <p>
        Stand: <Platzhalter>Datum der letzten Aktualisierung</Platzhalter>
      </p>

      <h2>Hinweis zur Vorlage</h2>
      <p>
        Dieser Text beschreibt die tatsächlich implementierte Verarbeitung, ist aber eine
        Vorlage und ersetzt keine Rechtsberatung. Alle gelb markierten Platzhalter sind vor
        einer Veröffentlichung zu ersetzen; der Text ist anschließend durch eine
        qualifizierte Stelle zu prüfen.
      </p>
    </article>
  );
}
