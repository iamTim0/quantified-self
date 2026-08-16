import type { ReactNode } from "react";

import type { Locale } from "../../lib/i18n/locale";
import { translate } from "../../lib/i18n/translate";
import { Placeholder, Sections, TranslationNotice } from "../parts";

/**
 * The privacy policy, in both interface languages.
 *
 * The German version is the binding one: it is written against the GDPR as applied
 * in Germany, cites the TDDDG, and is one of the two exceptions rule 16 of AGENTS.md
 * names for German prose outside the message catalogue. The English version is a
 * courtesy translation and says so.
 *
 * Both describe the processing this application actually performs, and the section
 * list below is what keeps them describing the same processing: each language is
 * typed `Record<SectionId, ReactNode>`, so a section present in one and missing from
 * the other does not compile. A policy that is current in one language and stale in
 * the other is worse than one language alone, because each reader believes theirs is
 * the accurate one.
 */
const SECTIONS = [
  "intro",
  "controller",
  "specialCategories",
  "account",
  "cookies",
  "connectors",
  "credentials",
  "analysis",
  "logs",
  "hosting",
  "externalSignIn",
  "disclosure",
  "retention",
  "rights",
  "security",
  "changes",
  "template",
] as const;

type SectionId = (typeof SECTIONS)[number];

export default function Privacy({ locale }: { locale: Locale }) {
  const german = locale === "de";

  return (
    <article>
      <h1>{german ? "Datenschutzerklärung" : "Privacy policy"}</h1>
      {!german && <TranslationNotice text={translate(locale, "legal.translationNote")} />}
      <Sections order={SECTIONS} sections={german ? de : en} />
    </article>
  );
}

const de: Record<SectionId, ReactNode> = {
  intro: (
    <p>
      Diese Erklärung beschreibt, welche personenbezogenen Daten in dieser Quantified-Self-Plattform
      verarbeitet werden, zu welchem Zweck und auf welcher Rechtsgrundlage. Sie beschreibt den
      tatsächlichen Stand der Anwendung.
    </p>
  ),

  controller: (
    <>
      <h2>1. Verantwortlicher</h2>
      <p>
        <Placeholder>Name bzw. Firma</Placeholder>
        <br />
        <Placeholder>Anschrift</Placeholder>
        <br />
        E-Mail: <Placeholder>datenschutz@example.org</Placeholder>
      </p>
      <p>
        Datenschutzbeauftragte Person:{" "}
        <Placeholder>
          Name und Kontakt, sofern eine Benennungspflicht nach Art. 37 DSGVO besteht — sonst diesen
          Absatz entfernen
        </Placeholder>
      </p>
    </>
  ),

  specialCategories: (
    <>
      <h2>2. Besondere Kategorien personenbezogener Daten</h2>
      <p>
        Diese Anwendung verarbeitet <strong>Gesundheitsdaten</strong> (z. B. Schlaf,
        Herzfrequenzvariabilität, Erholung, Training, Ernährung) sowie{" "}
        <strong>Standortdaten</strong>. Gesundheitsdaten sind besondere Kategorien personenbezogener
        Daten im Sinne von Art. 9 Abs. 1 DSGVO.
      </p>
      <p>
        Ihre Verarbeitung erfolgt ausschließlich auf Grundlage Ihrer ausdrücklichen Einwilligung
        nach Art. 9 Abs. 2 lit. a DSGVO. Sie erteilen diese Einwilligung, indem Sie einen Connector
        einrichten oder Daten selbst hochladen. Sie können sie jederzeit mit Wirkung für die Zukunft
        widerrufen, indem Sie den Connector entfernen oder Ihr Konto löschen.
      </p>
    </>
  ),

  account: (
    <>
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
        Datenbankabfragen sind auf diesen Arbeitsbereich eingeschränkt; ein Zugriff auf Daten
        anderer Arbeitsbereiche ist technisch ausgeschlossen, sofern nicht über die Freigabefunktion
        ausdrücklich eine Freigabe erteilt wurde.
      </p>
      <p>Rechtsgrundlage: Art. 6 Abs. 1 lit. b DSGVO (Erfüllung des Nutzungsvertrags).</p>
    </>
  ),

  cookies: (
    <>
      <h2>4. Anmeldung, Sitzungen und Cookies</h2>
      <p>
        Für die Anmeldung setzt diese Anwendung technisch notwendige Cookies. Es werden keine
        Cookies zu Werbe-, Tracking- oder Analysezwecken verwendet und keine Daten an Dritte
        weitergegeben. Gesetzt werden:
      </p>
      <div className="overflow-x-auto">
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
              Zufallswert zum Schutz vor Cross-Site-Request-Forgery. Kein Zugangstoken: er erlaubt
              für sich genommen keinen Zugriff auf Daten.
            </td>
            <td>Secure, SameSite=Lax, für die Oberfläche lesbar</td>
            <td>30 Tage</td>
          </tr>
          <tr>
            <td>
              <code>qs-locale</code>
            </td>
            <td>
              Die gewählte Anzeigesprache (<code>de</code> oder <code>en</code>). Enthält keine
              personenbezogenen Daten.
            </td>
            <td>SameSite=Lax, für die Oberfläche lesbar</td>
            <td>1 Jahr</td>
          </tr>
        </tbody>
      </table>
      </div>
      <p>
        <code>HttpOnly</code> bedeutet, dass die beiden Zugangs-Cookies für JavaScript im Browser
        nicht lesbar sind. Sie können damit auch bei einer Sicherheitslücke in der Oberfläche nicht
        ausgelesen und an Dritte übertragen werden.
      </p>
      <p>
        Diese Cookies sind für den Betrieb des von Ihnen ausdrücklich angeforderten Dienstes
        unbedingt erforderlich (§ 25 Abs. 2 Nr. 2 TDDDG) und bedürfen daher keiner gesonderten
        Einwilligung. Beim Abmelden werden alle genannten Cookies gelöscht und die zugehörige
        Sitzung zusätzlich serverseitig ungültig gemacht.
      </p>
      <p>
        Zusätzlich wird beim Anmelden über einen externen Anbieter kurzzeitig der Name des gewählten
        Anbieters im <code>sessionStorage</code> des Browsers abgelegt, damit die Rückleitung dem
        richtigen Anbieter zugeordnet werden kann. Dieser Eintrag enthält keine personenbezogenen
        Daten und wird nach Abschluss der Anmeldung entfernt.
      </p>
      <p>
        Ein Erneuerungstoken ist nur einmal verwendbar. Wird ein bereits verbrauchtes Token erneut
        vorgelegt, werden vorsorglich sämtliche Sitzungen des Kontos beendet.
      </p>
    </>
  ),

  connectors: (
    <>
      <h2>5. Daten aus verbundenen Diensten</h2>
      <p>
        Sie entscheiden selbst, welche Connectoren Sie einrichten. Ohne Einrichtung werden keine
        Daten von Dritten abgerufen. Je nach Auswahl werden verarbeitet:
      </p>
      <div className="overflow-x-auto">
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
      </div>
      <p>
        Rechtsgrundlage: Art. 6 Abs. 1 lit. a und Art. 9 Abs. 2 lit. a DSGVO (Einwilligung), erteilt
        durch die Einrichtung des jeweiligen Connectors.
      </p>
      <p>
        Beim Abruf werden Ihre Daten von den jeweiligen Anbietern an die Plattform übermittelt. Für
        deren eigene Verarbeitung gelten die Datenschutzhinweise des jeweiligen Anbieters. Prüfen
        Sie insbesondere, ob dabei eine Übermittlung in Drittländer stattfindet.
      </p>
    </>
  ),

  credentials: (
    <>
      <h2>6. Zugangsdaten zu verbundenen Diensten</h2>
      <p>
        Zugangstoken und API-Schlüssel, die Sie für Connectoren hinterlegen, werden symmetrisch
        verschlüsselt gespeichert (Fernet, AES-256). In der Oberfläche und in allen API-Antworten
        erscheinen sie ausschließlich maskiert. Sie werden nicht protokolliert und nicht im Klartext
        über den Nachrichtenbus übertragen.
      </p>
      <p>
        Von der Plattform erzeugte API-Schlüssel für eingehende Daten werden{" "}
        <strong>ausschließlich als Hashwert</strong> gespeichert. Der vollständige Schlüssel wird
        genau einmal bei der Erstellung angezeigt und ist danach technisch nicht mehr abrufbar.
      </p>
      <p>
        Die URL eines privaten Kalender-Feeds ist selbst ein Zugangsgeheimnis. Sie wird daher wie
        ein Zugangsdatum behandelt und niemals vollständig protokolliert.
      </p>
    </>
  ),

  analysis: (
    <>
      <h2>7. Mess-, Analyse- und Qualitätsdaten</h2>
      <p>
        Importierte Messwerte werden mit Zeitstempel, Metrikart, Quelle, Wert und Metadaten
        gespeichert. Daraus werden auf Ihren Wunsch statistische Auswertungen berechnet,
        insbesondere Korrelationen zwischen Metriken, Trends sowie Angaben zu Datenlücken und
        Quellenkonflikten.
      </p>
      <p>
        Diese Auswertungen sind rein statistisch. Sie beschreiben Zusammenhänge, nicht Ursachen, und
        stellen <strong>keine medizinische Diagnose, Beratung oder Behandlungsempfehlung</strong>{" "}
        dar. Es findet keine automatisierte Entscheidungsfindung im Sinne von Art. 22 DSGVO statt.
      </p>
      <p>
        Zusätzlich wird protokolliert, wann welcher Import mit welchem Zeitfenster ausgeführt wurde
        und wie viele Datenpunkte dabei neu waren. Dieses Importprotokoll dient der
        Nachvollziehbarkeit und der Vermeidung von Datenlücken.
      </p>
    </>
  ),

  logs: (
    <>
      <h2>8. Protokolldaten und Betrieb</h2>
      <p>
        Zur Fehlersuche und Betriebssicherheit werden technische Protokolle erzeugt. Sie enthalten
        Zeitpunkt, angefragten Endpunkt, HTTP-Statuscode, Dauer, die Kennung des Arbeitsbereichs
        sowie eine zufällige Anfragekennung (<code>X-Request-ID</code>), über die eine Anfrage
        dienstübergreifend nachvollzogen werden kann.
      </p>
      <p>
        Zugangsdaten, Token und API-Schlüssel werden nicht protokolliert. Der Webserver bzw. die
        Hosting-Infrastruktur kann darüber hinaus Zugriffsprotokolle inklusive IP-Adresse führen.
      </p>
      <p>
        Zum Schutz vor dem automatisierten Durchprobieren von Passwörtern werden{" "}
        <strong>fehlgeschlagene Anmeldeversuche</strong> gezählt. Gespeichert werden ausschließlich
        der Zeitpunkt und ein <strong>SHA-256-Hashwert</strong> der eingegebenen E-Mail-Adresse
        sowie der IP-Adresse — nicht die Werte selbst. Für die Zählung genügt der Vergleich zweier
        Hashwerte; im Klartext wäre dies ein Verzeichnis aller Adressen, unter denen jemand eine
        Anmeldung versucht hat. Die Einträge werden nach <strong>15 Minuten</strong> automatisch
        gelöscht, eine erfolgreiche Anmeldung löscht die Einträge des betreffenden Kontos sofort.
      </p>
      <p>
        Rechtsgrundlage: Art. 6 Abs. 1 lit. f DSGVO (berechtigtes Interesse an einem sicheren und
        funktionsfähigen Betrieb).
      </p>
      <p>
        Aufbewahrungsdauer der Protokolle:{" "}
        <Placeholder>tatsächliche Aufbewahrungsdauer eintragen, z. B. 14 Tage</Placeholder>
      </p>
    </>
  ),

  hosting: (
    <>
      <h2>9. Hosting und Auftragsverarbeitung</h2>
      <p>
        Die Anwendung wird betrieben bei:{" "}
        <Placeholder>Name und Anschrift des Hosting-Anbieters, Serverstandort</Placeholder>
      </p>
      <p>
        Mit dem Anbieter besteht ein Vertrag zur Auftragsverarbeitung nach Art. 28 DSGVO. Sofern
        eine Verarbeitung außerhalb der EU/des EWR stattfindet, ist hier die Grundlage der
        Übermittlung anzugeben:{" "}
        <Placeholder>z. B. Standardvertragsklauseln oder Angemessenheitsbeschluss</Placeholder>.
      </p>
      <p>
        Weitere eingesetzte Auftragsverarbeiter:{" "}
        <Placeholder>
          auflisten, z. B. Monitoring, Backup oder E-Mail-Versand — oder Abschnitt entfernen, wenn
          keine bestehen
        </Placeholder>
      </p>
    </>
  ),

  externalSignIn: (
    <>
      <h2>10. Externe Anmeldedienste</h2>
      <p>
        Die Anmeldung über externe Anbieter (OpenID Connect, etwa ein Google-Konto) ist vorhanden,
        aber <strong>standardmäßig nicht eingerichtet</strong>: solange keine Anbieter hinterlegt
        sind, erfolgt die Anmeldung ausschließlich mit E-Mail-Adresse und Passwort.
      </p>
      <p>
        Wird ein Anbieter eingerichtet, werden von ihm die Kennung des Kontos beim Anbieter (
        <code>sub</code>), die E-Mail-Adresse und, sofern übermittelt, der Anzeigename verarbeitet —
        zu dem Zweck, das Konto wiederzuerkennen. Rechtsgrundlage ist Art. 6 Abs. 1 lit. b DSGVO.
        Die Zuordnung erfolgt über die Anbieterkennung, nicht über die E-Mail-Adresse.
      </p>
      <p>
        Vor der Aktivierung ist dieser Abschnitt um die konkret eingerichteten Anbieter zu ergänzen:{" "}
        <Placeholder>
          Anbieter, übermittelte Daten und etwaige Drittlandübermittlung auflisten — oder diesen
          Hinweis entfernen, wenn keine Anbieter eingerichtet sind
        </Placeholder>
      </p>
    </>
  ),

  disclosure: (
    <>
      <h2>11. Weitergabe an Dritte</h2>
      <p>Eine Weitergabe Ihrer Daten findet nicht statt, mit folgenden Ausnahmen:</p>
      <ul>
        <li>an von Ihnen selbst eingerichtete Connectoren, soweit für den Abruf erforderlich;</li>
        <li>an Auftragsverarbeiter nach Abschnitt 9;</li>
        <li>
          an andere Arbeitsbereiche, wenn Sie über die Freigabefunktion ausdrücklich eine Freigabe
          erteilen — diese können Sie jederzeit widerrufen;
        </li>
        <li>soweit eine gesetzliche Verpflichtung besteht.</li>
      </ul>
      <p>Ein Verkauf von Daten oder eine Nutzung für Werbung findet nicht statt.</p>
    </>
  ),

  retention: (
    <>
      <h2>12. Speicherdauer</h2>
      <ul>
        <li>Konto- und Messdaten: bis zur Löschung durch Sie oder bis zur Löschung des Kontos.</li>
        <li>Erneuerungstoken: 30 Tage, bei Abmeldung sofort ungültig.</li>
        <li>
          Sperrliste abgemeldeter Zugriffstoken: bis zum ohnehin eintretenden Ablauf des Tokens;
          danach automatische Bereinigung.
        </li>
        <li>
          Technische Protokolle: <Placeholder>Aufbewahrungsdauer wie in Abschnitt 8</Placeholder>.
        </li>
      </ul>
    </>
  ),

  rights: (
    <>
      <h2>13. Ihre Rechte</h2>
      <p>Sie haben nach der DSGVO folgende Rechte:</p>
      <ul>
        <li>Auskunft über die verarbeiteten Daten (Art. 15)</li>
        <li>Berichtigung unrichtiger Daten (Art. 16)</li>
        <li>Löschung (Art. 17)</li>
        <li>Einschränkung der Verarbeitung (Art. 18)</li>
        <li>Datenübertragbarkeit (Art. 20)</li>
        <li>Widerspruch gegen Verarbeitungen auf Grundlage berechtigter Interessen (Art. 21)</li>
        <li>Widerruf erteilter Einwilligungen mit Wirkung für die Zukunft (Art. 7 Abs. 3)</li>
      </ul>
      <p>Innerhalb der Anwendung können Sie unmittelbar:</p>
      <ul>
        <li>einzelne Connectoren samt gespeicherter Zugangsdaten entfernen,</li>
        <li>API-Schlüssel widerrufen,</li>
        <li>sämtliche importierten Messdaten löschen,</li>
        <li>Ihr Konto vollständig löschen.</li>
      </ul>
      <p>
        Sie haben außerdem das Recht, sich bei einer Datenschutz-Aufsichtsbehörde zu beschweren,
        insbesondere in dem Mitgliedstaat Ihres Aufenthaltsorts oder des mutmaßlichen Verstoßes.
        Zuständige Behörde für den Verantwortlichen:{" "}
        <Placeholder>zuständige Aufsichtsbehörde mit Anschrift</Placeholder>
      </p>
    </>
  ),

  security: (
    <>
      <h2>14. Datensicherheit</h2>
      <ul>
        <li>Übertragung ausschließlich über TLS.</li>
        <li>Passwörter als bcrypt-Hash, API-Schlüssel als SHA-256-Hash gespeichert.</li>
        <li>Connector-Zugangsdaten mit Fernet (AES-256) verschlüsselt.</li>
        <li>
          Jede Anfrage wird serverseitig authentifiziert; die Zuordnung zum Arbeitsbereich wird
          ausschließlich aus dem geprüften Token abgeleitet und nicht aus frei setzbaren Kopfzeilen.
        </li>
        <li>Interne Schnittstellen sind von außen nicht erreichbar.</li>
      </ul>
    </>
  ),

  changes: (
    <>
      <h2>15. Änderungen dieser Erklärung</h2>
      <p>
        Diese Erklärung wird angepasst, wenn sich die Verarbeitung ändert. Maßgeblich ist die
        jeweils hier veröffentlichte Fassung.
      </p>
      <p>
        Stand: <Placeholder>Datum der letzten Aktualisierung</Placeholder>
      </p>
    </>
  ),

  template: (
    <>
      <h2>Hinweis zur Vorlage</h2>
      <p>
        Dieser Text beschreibt die tatsächlich implementierte Verarbeitung, ist aber eine Vorlage
        und ersetzt keine Rechtsberatung. Alle gelb markierten Platzhalter sind vor einer
        Veröffentlichung zu ersetzen; der Text ist anschließend durch eine qualifizierte Stelle zu
        prüfen.
      </p>
    </>
  ),
};

const en: Record<SectionId, ReactNode> = {
  intro: (
    <p>
      This policy describes which personal data this Quantified Self platform processes, for what
      purpose, and on what legal basis. It describes what the application actually does.
    </p>
  ),

  controller: (
    <>
      <h2>1. Controller</h2>
      <p>
        <Placeholder>Name or company</Placeholder>
        <br />
        <Placeholder>Address</Placeholder>
        <br />
        Email: <Placeholder>datenschutz@example.org</Placeholder>
      </p>
      <p>
        Data protection officer:{" "}
        <Placeholder>
          Name and contact details, where Art. 37 GDPR requires one to be appointed — otherwise
          remove this paragraph
        </Placeholder>
      </p>
    </>
  ),

  specialCategories: (
    <>
      <h2>2. Special categories of personal data</h2>
      <p>
        This application processes <strong>health data</strong> (sleep, heart-rate variability,
        recovery, training, nutrition, for example) and <strong>location data</strong>. Health data
        is a special category of personal data within the meaning of Art. 9 (1) GDPR.
      </p>
      <p>
        It is processed solely on the basis of your explicit consent under Art. 9 (2) (a) GDPR. You
        give that consent by setting up a connector or by uploading data yourself. You can withdraw
        it at any time with effect for the future, by removing the connector or deleting your
        account.
      </p>
    </>
  ),

  account: (
    <>
      <h2>3. Account and workspace</h2>
      <p>Registration processes:</p>
      <ul>
        <li>Email address (it serves as the sign-in name)</li>
        <li>Display name</li>
        <li>Password — stored only as a bcrypt hash, never in the clear</li>
        <li>Role within the workspace (owner, admin, member)</li>
        <li>The time the account was created</li>
      </ul>
      <p>
        Every account belongs to exactly one workspace (a &ldquo;tenant&rdquo;). Every database
        query is restricted to that workspace; access to another workspace&rsquo;s data is
        technically impossible unless a grant was explicitly issued through the sharing feature.
      </p>
      <p>Legal basis: Art. 6 (1) (b) GDPR (performance of the contract of use).</p>
    </>
  ),

  cookies: (
    <>
      <h2>4. Sign-in, sessions and cookies</h2>
      <p>
        This application sets technically necessary cookies for signing in. No cookies are used for
        advertising, tracking or analytics, and no data is passed to third parties. The cookies set
        are:
      </p>
      <div className="overflow-x-auto">
      <table>
        <thead>
          <tr>
            <th>Name</th>
            <th>Contents</th>
            <th>Attributes</th>
            <th>Storage period</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>
              <code>qs_access</code>
            </td>
            <td>A signed access token (JWT) naming the user, the tenant and the role</td>
            <td>HttpOnly, Secure, SameSite=Lax</td>
            <td>12 hours</td>
          </tr>
          <tr>
            <td>
              <code>qs_refresh</code>
            </td>
            <td>A random refresh token; stored server-side only as a hash</td>
            <td>HttpOnly, Secure, SameSite=Lax, sent only to the sign-in endpoints</td>
            <td>30 days</td>
          </tr>
          <tr>
            <td>
              <code>qs_csrf</code>
            </td>
            <td>
              A random value protecting against cross-site request forgery. Not an access token: on
              its own it grants no access to any data.
            </td>
            <td>Secure, SameSite=Lax, readable by the interface</td>
            <td>30 days</td>
          </tr>
          <tr>
            <td>
              <code>qs-locale</code>
            </td>
            <td>
              The chosen interface language (<code>de</code> or <code>en</code>). Contains no
              personal data.
            </td>
            <td>SameSite=Lax, readable by the interface</td>
            <td>1 year</td>
          </tr>
        </tbody>
      </table>
      </div>
      <p>
        <code>HttpOnly</code> means the two access cookies cannot be read by JavaScript in the
        browser. They therefore cannot be read out and passed to a third party even if the interface
        has a security flaw.
      </p>
      <p>
        These cookies are strictly necessary to provide the service you explicitly requested (§ 25
        (2) no. 2 TDDDG) and so require no separate consent. Signing out deletes every cookie named
        above and additionally invalidates the session server-side.
      </p>
      <p>
        When signing in through an external provider, the name of the chosen provider is also held
        briefly in the browser&rsquo;s <code>sessionStorage</code>, so that the redirect back can be
        matched to the right provider. That entry contains no personal data and is removed once the
        sign-in completes.
      </p>
      <p>
        A refresh token can be used only once. If a token that has already been spent is presented
        again, every session of the account is ended as a precaution.
      </p>
    </>
  ),

  connectors: (
    <>
      <h2>5. Data from connected services</h2>
      <p>
        You decide which connectors you set up. Without one, no data is retrieved from any third
        party. Depending on your choices, the following is processed:
      </p>
      <div className="overflow-x-auto">
      <table>
        <thead>
          <tr>
            <th>Connector</th>
            <th>Kinds of data</th>
            <th>Retrieval</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>WHOOP</td>
            <td>Recovery, sleep, strain, workouts</td>
            <td>Retrieved by the platform</td>
          </tr>
          <tr>
            <td>Yazio</td>
            <td>Food diary, calories, macronutrients</td>
            <td>Retrieved by the platform</td>
          </tr>
          <tr>
            <td>Dawarich</td>
            <td>GPS location points and movement traces</td>
            <td>Retrieved by the platform</td>
          </tr>
          <tr>
            <td>Calendar (ICS)</td>
            <td>Events, titles, duration, busy time</td>
            <td>Retrieved by the platform</td>
          </tr>
          <tr>
            <td>Home Assistant, weather</td>
            <td>Sensor and environmental values</td>
            <td>Retrieved by the platform</td>
          </tr>
          <tr>
            <td>Apple Health</td>
            <td>Activity, vitals, sleep, workouts</td>
            <td>Sent by your device</td>
          </tr>
          <tr>
            <td>Streak</td>
            <td>Strength training, sets, repetitions, weights</td>
            <td>Sent by your app</td>
          </tr>
        </tbody>
      </table>
      </div>
      <p>
        Legal basis: Art. 6 (1) (a) and Art. 9 (2) (a) GDPR (consent), given by setting up the
        connector in question.
      </p>
      <p>
        On retrieval, your data is transmitted to the platform by the respective providers. Their
        own processing is governed by their own privacy notices. Check in particular whether that
        involves a transfer to a third country.
      </p>
    </>
  ),

  credentials: (
    <>
      <h2>6. Credentials for connected services</h2>
      <p>
        Access tokens and API keys you store for connectors are kept under symmetric encryption
        (Fernet, AES-256). They appear only masked in the interface and in every API response. They
        are not logged, and they are not transmitted in the clear over the message bus.
      </p>
      <p>
        API keys the platform issues for inbound data are stored <strong>only as a hash</strong>.
        The full key is shown exactly once, when it is created, and afterwards cannot technically be
        retrieved.
      </p>
      <p>
        The URL of a private calendar feed is itself a secret. It is therefore treated as a
        credential and never logged in full.
      </p>
    </>
  ),

  analysis: (
    <>
      <h2>7. Measurement, analysis and quality data</h2>
      <p>
        Imported measurements are stored with a timestamp, the kind of metric, the source, the value
        and metadata. At your request, statistical analyses are computed from them — in particular
        correlations between metrics, trends, and figures on data gaps and source conflicts.
      </p>
      <p>
        These analyses are purely statistical. They describe relationships, not causes, and
        constitute <strong>no medical diagnosis, advice or treatment recommendation</strong>. There
        is no automated decision-making within the meaning of Art. 22 GDPR.
      </p>
      <p>
        It is additionally recorded which import ran when, over which window, and how many data
        points were new. That import log serves traceability and the avoidance of gaps in the data.
      </p>
    </>
  ),

  logs: (
    <>
      <h2>8. Log data and operation</h2>
      <p>
        Technical logs are produced for debugging and operational security. They contain the time,
        the endpoint requested, the HTTP status code, the duration, the workspace identifier, and a
        random request identifier (<code>X-Request-ID</code>) through which a request can be
        followed across services.
      </p>
      <p>
        Credentials, tokens and API keys are not logged. The web server or hosting infrastructure
        may additionally keep access logs including the IP address.
      </p>
      <p>
        To protect against automated password guessing, <strong>failed sign-in attempts</strong>{" "}
        are counted. Only the time and a <strong>SHA-256 hash</strong> of the submitted email
        address and of the IP address are stored — not the values themselves. Counting needs
        nothing more than a comparison of two hashes; in plain text this would be a record of every
        address anyone had tried to sign in as. Entries are deleted automatically after{" "}
        <strong>15 minutes</strong>, and a successful sign-in clears that account&rsquo;s entries
        immediately.
      </p>
      <p>
        Legal basis: Art. 6 (1) (f) GDPR (legitimate interest in secure and functioning operation).
      </p>
      <p>
        Retention period for the logs:{" "}
        <Placeholder>enter the actual retention period, e.g. 14 days</Placeholder>
      </p>
    </>
  ),

  hosting: (
    <>
      <h2>9. Hosting and processing on our behalf</h2>
      <p>
        The application is operated at:{" "}
        <Placeholder>Name and address of the hosting provider, server location</Placeholder>
      </p>
      <p>
        A data processing agreement under Art. 28 GDPR is in place with that provider. Where
        processing takes place outside the EU/EEA, state the basis for the transfer here:{" "}
        <Placeholder>e.g. standard contractual clauses or an adequacy decision</Placeholder>.
      </p>
      <p>
        Further processors used:{" "}
        <Placeholder>
          list them, e.g. monitoring, backup or email delivery — or remove the section if there are
          none
        </Placeholder>
      </p>
    </>
  ),

  externalSignIn: (
    <>
      <h2>10. External sign-in services</h2>
      <p>
        Signing in through an external provider (OpenID Connect, a Google account for instance) is
        available but <strong>not configured by default</strong>: as long as no provider is set up,
        signing in works with an email address and a password only.
      </p>
      <p>
        Where a provider is set up, the account identifier at that provider (<code>sub</code>), the
        email address and, if supplied, the display name are processed — for the purpose of
        recognizing the account again. The legal basis is Art. 6 (1) (b) GDPR. The account is
        matched on the provider identifier, not on the email address.
      </p>
      <p>
        Before activation, complete this section with the providers actually configured:{" "}
        <Placeholder>
          list the providers, the data they transmit and any third-country transfer — or remove this
          note if no provider is configured
        </Placeholder>
      </p>
    </>
  ),

  disclosure: (
    <>
      <h2>11. Disclosure to third parties</h2>
      <p>Your data is not disclosed, with the following exceptions:</p>
      <ul>
        <li>to connectors you set up yourself, insofar as retrieval requires it;</li>
        <li>to the processors named in section 9;</li>
        <li>
          to other workspaces, where you explicitly issue a grant through the sharing feature —
          which you can withdraw at any time;
        </li>
        <li>insofar as a legal obligation exists.</li>
      </ul>
      <p>Data is not sold, and is not used for advertising.</p>
    </>
  ),

  retention: (
    <>
      <h2>12. Storage periods</h2>
      <ul>
        <li>Account and measurement data: until you delete it, or until the account is deleted.</li>
        <li>Refresh tokens: 30 days, invalidated immediately on sign-out.</li>
        <li>
          The denylist of signed-out access tokens: until the token would have expired anyway;
          cleaned up automatically after that.
        </li>
        <li>
          Technical logs: <Placeholder>the retention period from section 8</Placeholder>.
        </li>
      </ul>
    </>
  ),

  rights: (
    <>
      <h2>13. Your rights</h2>
      <p>Under the GDPR you have the following rights:</p>
      <ul>
        <li>Access to the data processed (Art. 15)</li>
        <li>Rectification of inaccurate data (Art. 16)</li>
        <li>Erasure (Art. 17)</li>
        <li>Restriction of processing (Art. 18)</li>
        <li>Data portability (Art. 20)</li>
        <li>Objection to processing based on legitimate interests (Art. 21)</li>
        <li>Withdrawal of consent, with effect for the future (Art. 7 (3))</li>
      </ul>
      <p>Within the application you can directly:</p>
      <ul>
        <li>remove individual connectors along with their stored credentials,</li>
        <li>revoke API keys,</li>
        <li>delete every imported measurement,</li>
        <li>delete your account entirely.</li>
      </ul>
      <p>
        You also have the right to lodge a complaint with a data protection supervisory authority,
        in particular in the member state of your residence or of the alleged infringement. The
        authority competent for the controller:{" "}
        <Placeholder>the competent supervisory authority, with its address</Placeholder>
      </p>
    </>
  ),

  security: (
    <>
      <h2>14. Data security</h2>
      <ul>
        <li>Transmission over TLS only.</li>
        <li>Passwords stored as a bcrypt hash, API keys as a SHA-256 hash.</li>
        <li>Connector credentials encrypted with Fernet (AES-256).</li>
        <li>
          Every request is authenticated server-side; the workspace it belongs to is derived solely
          from the validated token, never from a freely settable header.
        </li>
        <li>Internal interfaces are not reachable from outside.</li>
      </ul>
    </>
  ),

  changes: (
    <>
      <h2>15. Changes to this policy</h2>
      <p>
        This policy is amended when the processing changes. The version published here at any given
        time is the one that applies.
      </p>
      <p>
        Last updated: <Placeholder>Date of the last update</Placeholder>
      </p>
    </>
  ),

  template: (
    <>
      <h2>A note on this template</h2>
      <p>
        This text describes the processing as it is actually implemented, but it is a template and
        is no substitute for legal advice. Every highlighted placeholder is to be replaced before
        publication, and the text is then to be reviewed by a qualified party.
      </p>
    </>
  ),
};
