import type { ReactNode } from "react";

import type { Locale } from "../../lib/i18n/locale";
import { translate } from "../../lib/i18n/translate";
import { Placeholder, Sections, TranslationNotice } from "../parts";

/**
 * The legal notice, in both interface languages.
 *
 * The German version is the binding one — it is drafted against § 5 DDG and
 * § 18 Abs. 2 MStV, which are German statutes, and it is one of the two exceptions
 * rule 16 of AGENTS.md names for German prose outside the message catalogue. The
 * English version exists so a reader who does not read German can tell what is
 * being disclosed, and it says so.
 *
 * Not routed as two URLs: `/legal/impressum` is what the footer, the documentation
 * and any external reference point at, and a legal notice that moves depending on
 * the reader's language is a link that rots.
 */
const SECTIONS = [
  "basis",
  "provider",
  "represented",
  "contact",
  "register",
  "vat",
  "supervisor",
  "profession",
  "responsible",
  "disputes",
  "liability",
  "template",
  "updated",
] as const;

type SectionId = (typeof SECTIONS)[number];

export default function Imprint({ locale }: { locale: Locale }) {
  const german = locale === "de";

  return (
    <article>
      <h1>{german ? "Impressum" : "Legal notice"}</h1>
      {!german && <TranslationNotice text={translate(locale, "legal.translationNote")} />}
      <Sections order={SECTIONS} sections={german ? de : en} />
    </article>
  );
}

const de: Record<SectionId, ReactNode> = {
  basis: <p>Angaben gemäß § 5 Digitale-Dienste-Gesetz (DDG).</p>,

  provider: (
    <>
      <h2>Anbieter</h2>
      <p>
        <Placeholder>Vollständiger Name bzw. Firma inkl. Rechtsform</Placeholder>
        <br />
        <Placeholder>Straße und Hausnummer</Placeholder>
        <br />
        <Placeholder>PLZ und Ort</Placeholder>
        <br />
        <Placeholder>Land</Placeholder>
      </p>
    </>
  ),

  represented: (
    <>
      <h2>Vertreten durch</h2>
      <p>
        <Placeholder>
          Name der vertretungsberechtigten Person(en); bei juristischen Personen alle
          Geschäftsführer bzw. Vorstandsmitglieder
        </Placeholder>
      </p>
    </>
  ),

  contact: (
    <>
      <h2>Kontakt</h2>
      <p>
        E-Mail: <Placeholder>kontakt@example.org</Placeholder>
        <br />
        Telefon: <Placeholder>Telefonnummer</Placeholder>
      </p>
      <p>
        Eine Telefonnummer ist nicht zwingend erforderlich, es muss aber ein zweiter,
        unmittelbarer Kommunikationsweg neben der E-Mail-Adresse bestehen (z. B.
        Kontaktformular mit zugesicherter Reaktionszeit).
      </p>
    </>
  ),

  register: (
    <>
      <h2>Registereintrag</h2>
      <p>
        Registergericht: <Placeholder>z. B. Amtsgericht Musterstadt</Placeholder>
        <br />
        Registernummer: <Placeholder>z. B. HRB 12345</Placeholder>
      </p>
      <p>
        Entfällt bei Privatpersonen und nicht eingetragenen Einzelunternehmen. Diesen
        Abschnitt dann bitte vollständig löschen statt leer zu lassen.
      </p>
    </>
  ),

  vat: (
    <>
      <h2>Umsatzsteuer-Identifikationsnummer</h2>
      <p>
        Umsatzsteuer-Identifikationsnummer gemäß § 27 a Umsatzsteuergesetz:{" "}
        <Placeholder>DE000000000</Placeholder>
      </p>
      <p>
        Bei Anwendung der Kleinunternehmerregelung (§ 19 UStG) besteht in der Regel keine
        USt-IdNr.; dieser Abschnitt entfällt dann.
      </p>
    </>
  ),

  supervisor: (
    <>
      <h2>Aufsichtsbehörde</h2>
      <p>
        <Placeholder>
          Nur erforderlich bei zulassungspflichtigen Tätigkeiten — zuständige
          Aufsichtsbehörde mit Anschrift
        </Placeholder>
      </p>
    </>
  ),

  profession: (
    <>
      <h2>Berufsrechtliche Angaben</h2>
      <p>
        <Placeholder>
          Nur bei reglementierten Berufen — gesetzliche Berufsbezeichnung, Staat der
          Verleihung, zuständige Kammer und maßgebliche berufsrechtliche Regelungen
        </Placeholder>
      </p>
    </>
  ),

  responsible: (
    <>
      <h2>Verantwortlich für den Inhalt nach § 18 Abs. 2 MStV</h2>
      <p>
        <Placeholder>Name</Placeholder>
        <br />
        <Placeholder>Anschrift, sofern abweichend von oben</Placeholder>
      </p>
    </>
  ),

  disputes: (
    <>
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
        <Placeholder>
          Angabe ergänzen, ob eine Teilnahme an einem Streitbeilegungsverfahren vor einer
          Verbraucherschlichtungsstelle erfolgt — die Angabe ist verpflichtend, auch wenn
          keine Teilnahme erfolgt
        </Placeholder>
      </p>
    </>
  ),

  liability: (
    <>
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
    </>
  ),

  template: (
    <>
      <h2>Hinweis zur Vorlage</h2>
      <p>
        Dieses Impressum ist eine Vorlage. Welche Angaben im Einzelfall erforderlich sind,
        hängt von Rechtsform, Tätigkeit und Zielmarkt ab. Bitte vor Veröffentlichung durch
        eine qualifizierte Stelle prüfen lassen und alle gelb markierten Platzhalter
        ersetzen oder die betreffenden Abschnitte entfernen.
      </p>
    </>
  ),

  updated: (
    <p>
      Stand: <Placeholder>Datum der letzten Aktualisierung</Placeholder>
    </p>
  ),
};

const en: Record<SectionId, ReactNode> = {
  basis: <p>Information pursuant to § 5 of the German Digital Services Act (DDG).</p>,

  provider: (
    <>
      <h2>Provider</h2>
      <p>
        <Placeholder>Full name or company, including legal form</Placeholder>
        <br />
        <Placeholder>Street and number</Placeholder>
        <br />
        <Placeholder>Postcode and town</Placeholder>
        <br />
        <Placeholder>Country</Placeholder>
      </p>
    </>
  ),

  represented: (
    <>
      <h2>Represented by</h2>
      <p>
        <Placeholder>
          Name of the authorized representative(s); for legal entities, every managing
          director or board member
        </Placeholder>
      </p>
    </>
  ),

  contact: (
    <>
      <h2>Contact</h2>
      <p>
        Email: <Placeholder>kontakt@example.org</Placeholder>
        <br />
        Telephone: <Placeholder>Telephone number</Placeholder>
      </p>
      <p>
        A telephone number is not strictly required, but there has to be a second, direct
        channel of communication besides the email address (a contact form with a promised
        response time, for instance).
      </p>
    </>
  ),

  register: (
    <>
      <h2>Register entry</h2>
      <p>
        Registering court: <Placeholder>e.g. Amtsgericht Musterstadt</Placeholder>
        <br />
        Register number: <Placeholder>e.g. HRB 12345</Placeholder>
      </p>
      <p>
        Does not apply to private individuals or unregistered sole traders. Delete this
        section entirely in that case, rather than leaving it empty.
      </p>
    </>
  ),

  vat: (
    <>
      <h2>VAT identification number</h2>
      <p>
        VAT identification number pursuant to § 27 a of the German VAT Act:{" "}
        <Placeholder>DE000000000</Placeholder>
      </p>
      <p>
        Under the small-business rule (§ 19 UStG) there is usually no VAT ID; this section
        then does not apply.
      </p>
    </>
  ),

  supervisor: (
    <>
      <h2>Supervisory authority</h2>
      <p>
        <Placeholder>
          Only required for activities that need a licence — the competent supervisory
          authority, with its address
        </Placeholder>
      </p>
    </>
  ),

  profession: (
    <>
      <h2>Professional regulations</h2>
      <p>
        <Placeholder>
          Only for regulated professions — the statutory professional title, the state that
          conferred it, the competent chamber and the professional rules that apply
        </Placeholder>
      </p>
    </>
  ),

  responsible: (
    <>
      <h2>Responsible for the content pursuant to § 18 (2) MStV</h2>
      <p>
        <Placeholder>Name</Placeholder>
        <br />
        <Placeholder>Address, if it differs from the one above</Placeholder>
      </p>
    </>
  ),

  disputes: (
    <>
      <h2>Dispute resolution</h2>
      <p>
        The European Commission provides a platform for online dispute resolution:{" "}
        <a href="https://ec.europa.eu/consumers/odr/" rel="noreferrer noopener" target="_blank">
          https://ec.europa.eu/consumers/odr/
        </a>
        .
      </p>
      <p>
        <Placeholder>
          State whether you take part in dispute resolution proceedings before a consumer
          arbitration body — the statement is mandatory even when you do not
        </Placeholder>
      </p>
    </>
  ),

  liability: (
    <>
      <h2>Liability for content and links</h2>
      <p>
        As a service provider we are responsible for our own content on these pages under
        the general laws. We are not, however, obliged to monitor third-party information
        that is transmitted or stored, or to investigate circumstances that point to
        unlawful activity.
      </p>
      <p>
        At the explicit instruction of its users, this application retrieves data from
        external services (see the privacy policy). The provider of each of those external
        services is solely responsible for its content.
      </p>
    </>
  ),

  template: (
    <>
      <h2>A note on this template</h2>
      <p>
        This legal notice is a template. Which details are required in a given case depends
        on the legal form, the activity and the target market. Have it reviewed by a
        qualified party before publication, and replace every highlighted placeholder or
        remove the section it is in.
      </p>
    </>
  ),

  updated: (
    <p>
      Last updated: <Placeholder>Date of the last update</Placeholder>
    </p>
  ),
};
