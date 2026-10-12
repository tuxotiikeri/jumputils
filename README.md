# Jumputils

Jumputils muodostaa DJ/SDJ- ja Countermovement Jump (CMJ) -HTML-raportteja Theia3D/Nexus-C3D-tiedostoista ja voimalevydatasta. CMJ:n oma strategy profile perustuu koko kehon voimaintegraatioon sekä sagittaalisiin nivelkulmiin, momentteihin, tehoihin ja työhön.

## Rakenne

```text
jumputils/
|-- app/
|   |-- main.py                 Graafinen käyttöliittymä
|   |-- cli.py                  Komentorivikäynnistys ja työnkulku
|   |-- config.py               Analyysin asetukset
|   |-- models.py               Kerrosten väliset tietomallit
|   |-- c3d/
|   |   |-- reader.py           C3D-tiedostojen lukeminen
|   |   |-- labels.py           Nexus/Theia-nimikkeiden tunnistus
|   |   |-- events.py           Maakontaktien tunnistus
|   |   `-- forceplate.py       Voimalevy-CSV ja C3D-voimakanavat
|   |-- protocols/
|   |   |-- common.py           Protokollien yhteinen tunnistus
|   |   |-- dj.py               Bilateraalinen Drop Jump
|   |   |-- sdj.py              Single-Leg Drop Jump 15/30 cm
|   |   `-- cmj.py              CMJ-protokolla ja laskenta-asetukset
|   |-- analysis/
|   |   |-- jump_metrics.py     Yksittäisen hypyn laskenta
|   |   `-- averaging.py        Keskiarvot, hajonnat ja käyrät
|   `-- reporting/
|       |-- html.py             Raportin HTML-rakenne
|       |-- plots.py            Matplotlib-kuvaajat
|       |-- exports.py          Yhteenveto- ja kontaktitiedostot
|       |-- formatting.py       Lukujen ja päivämäärien muotoilu
|       |-- style.py            Värit ja kuvaajien tyylit
|       `-- templates/          Tulevat ulkoiset HTML/CSS-pohjat
|-- tests/                       Kevyet automaattiset testit
|-- data/                        Paikallinen mittausdata, ei GitHubiin
|-- reports/                     Muodostetut raportit, ei GitHubiin
|-- env/                         Konekohtainen Conda-ympäristö, ei GitHubiin
|-- environment.yml             Testattu Conda-ympäristö
|-- requirements.txt            Vastaavat suorat Python-riippuvuudet
|-- SETUP_jumputils.bat          Luo tai päivittää env-kansion
`-- run.bat                      Käynnistää käyttöliittymän
```

## Asennus Windows-koneelle

1. Asenna Miniconda tai Anaconda, jos koneella ei vielä ole Condaa.
2. Kloonaa tai kopioi tämä repositorio mihin tahansa pysyvään kansioon.
3. Suorita `SETUP_jumputils.bat` kerran. Se rakentaa `env`-kansion repositorion juureen.
4. Käynnistä ohjelma tiedostolla `run.bat`.

Polut ratkaistaan suhteessa repositorion sijaintiin. Projekti toimii siksi esimerkiksi sekä `C:\jumputils`- että `D:\Sovellukset\jumputils`-polusta ilman lähdekoodin muuttamista.

## Raportin luominen

Valitse mittauskansio, kirjoita mitattavan nimi ja paina **Create report**. CMJ:n perusraportti avautuu PDF:nä, DJ/SDJ HTML:nä. Jos kansiossa on molempia, molemmat erilliset raportit avataan. Raportit ja laskentaviennit tallennetaan `reports`-kansioon.

Valitun kansion alikansiot tutkitaan automaattisesti. C3D- ja raakavoima-CSV-tiedostoilla tulee olla sama nimi, esimerkiksi `DJ_1.c3d` ja `DJ_1.csv`.

## Kehittäminen

Komentorivikäyttö:

```bat
env\python.exe -m app.cli DATAKANSIO --subject "Test Person" --output reports\test.html
```

Automaattiset testit:

```bat
env\python.exe -m unittest discover -v
```

## CMJ-analyysi

Tiedostonimet `CMJ_1.c3d`, `CMJ_2.c3d` jne. tunnistetaan automaattisesti (myös pienet kirjaimet ja `.C3D`). Myös pelkät Nexus-voimalevy-CSV:t `CMJ_1.csv` jne. toimivat ilman C3D:tä tai Theiaa. Samanniminen C3D+CSV-pari käsitellään yhtenä suorituksena.

**CMJ Performance Report** on yhden A4-sivun PDF tavalliselle 1–6 trialin mittaukselle. Arial-fontti, Metropolian oranssi otsake ja pyöristetyt performance-kortit mukailevat DJ-raporttia. Summary säilyttää kaikkien trialien arvot ja mean ± SD:n. Suurimman hyppykorkeuden trialin otsikon yläpuolella on oranssi Best Jump -merkintä. Voimakäyrä esittää tästä trialista vasemman ja oikean jalan sekä yhdistetyn voiman liikkeen alusta irtoamiseen. Vain huippuvoima merkitään; braking ja propulsion näkyvät taustaväreinä nettovoimaimpulsseineen. Normalisoidut braking- ja propulsion-kuvaajat säilyttävät kaikkien trialien käyrät samalla voima-asteikolla kuin pääkuva. Metatietolaatikossa ovat päivä, massa, trialien määrä ja suodatus. Yli kuusi trialia jaetaan lisäsivuille.

Laaja HTML-raportti niveltyöstä, tehoista, thoraxista ja sekvensoinnista jää rinnalle nimellä `_extended.html`, kun liikeanalyysikanavia on käytettävissä. `--cmj-report performance|extended|both` valitsee sisällön (oletus `performance`; laaja liikeanalyysi vain erikseen valittaessa). Voimalevydatasta tehdään perusraportti ilman liikeanalyysisivuja. Virheelliset tiedostot ja analyysin huomautukset kirjataan lokiin ja JSON-vientiin.

Graafisen käyttöliittymän **Create report** tunnistaa CMJ:t automaattisesti. Jos kansiossa on myös DJ/SDJ-suorituksia, syntyy kaksi raporttia: pyydetty DJ/SDJ-raportti ja sen vierelle `_cmj.pdf` sekä HTML-esikatselu. Molemmat raportit avataan, ja DJ-raportissa on myös linkki CMJ-PDF:ään. Pelkistä CMJ-tiedostoista syntyy suoraan CMJ-raportti.

```bat
env\python.exe -m app.cli data\kuura --protocol cmj --subject "Kuura" --output reports\kuura_cmj.html
```

CMJ Performance Report käyttää aina samannimistä raakavoima-CSV:tä sekä COM-dynamiikkaan, impulsseihin että tapahtumiin. C3D:tä ei lueta tässä työnkulussa. Voimaan ei lisätä suodatusta oletuksena. Puuttuvan CSV:n tilalle ei oteta Nexuksen 15 Hz suodatettua C3D-voimaa; puuttumisesta ilmoitetaan lokissa ja käyttöliittymässä. Pelkät CMJ-CSV:t toimivat myös ilman C3D:tä. Molempien levyjen vertikaalinen voima summataan. Oletuslevyt ovat vasen 4 / oikea 3; muuta tarvittaessa `--plate-left` ja `--plate-right`. Erillinen asiantuntijakäyttö `--cmj-report extended` säilyttää C3D-liikeanalyysin. `both` käyttää raakavoima-CSV:tä laskentaan ja C3D:tä nivelkanaviin.

Voimadatassa on oltava vakaa seisontajakso ennen hyppyä. Oletuksena valitaan automaattisesti viimeinen hyväksytty 1 sekunnin jakso ennen kevennystä. Aloituksen ja keston voi määrittää:

```bat
env\python.exe -m app.cli DATAKANSIO --protocol cmj --cmj-baseline-start 1.0 --cmj-baseline-duration 1.0 --output reports\cmj.html
```

`--cmj-baseline-max-cv` määrittää seisontavoiman vaihtelu- ja trendirajan (oletus 0.02 eli 2 %). Tomin testiaineisto käyttää erikseen kirjattua 5 %:n rajaa, sillä tallenteissa on ennen hyppyä painon tasaamista. Lähtötason valinta vaikuttaa integroituihin korkeuksiin ja syvyyksiin; lyhyellä vakaalla jaksolla ei tule peittää pitkäkestoista huojuntaa.

```bat
env\python.exe -m app.cli data\tom_28_09_2026 --protocol cmj --cmj-report performance --cmj-force-source csv --body-mass 81 --cmj-baseline-max-cv 0.05 --measurement-date 2026-09-28 --subject Tom --output reports\tom_cmj_performance.pdf
```

`performance` + `csv` lukee tässä työnkulussa vain CSV-tiedostot, vaikka rinnalla olisi C3D:itä. Nivelkulmia tai momentteja ei lueta.

CSV:n `Frame`/`Sub Frame` kohdistetaan C3D:n alkuperäisiin kehysnumeroihin. CSV:n tapahtumat tunnistetaan sen alkuperäisellä aikaruudukolla, myös näytetaajuuden poiketessa C3D:stä. COM-laskentaan valitun voimasignaalin on katettava seisontajakso ja koko hyppy irtoamiseen asti. Puuttuvien nivelkanavien tai katkenneen liikevaiheen tilalle ei lasketa nollia eikä ekstrapoloida dataa; voimaperusteiset performance-tulokset säilyvät, jos voimadata on riittävä.

CMJ:n oletusmomenttiprofiili on laboratorion Nexus-export: ulkoiset momentit Nmm/kg. Momentit muunnetaan sisäisiksi, fleksio/dorsifleksio-positiivisiksi momenteiksi ennen teholaskentaa (kertoimet `-1 -1 -1`). Nexus voi ilmoittaa C3D-metatiedoissa `Nmm`, vaikka arvot on jo normalisoitu massaan. Muun vientimuodon yksiköt ja etumerkit määritetään eksplisiittisesti:

```bat
env\python.exe -m app.cli DATAKANSIO --protocol cmj --cmj-report extended --cmj-moment-unit Nm/kg --cmj-moment-signs 1 1 1 --output reports\cmj.html
```

Voimaan ei lisätä suodatusta oletusarvoisesti (`--cmj-force-filter-hz 0`). Myös raakavoiman eventtunnistus toimii ilman lisäsuodatusta. Laajan raportin kulmat ja momentit saavat oletuksena 10 Hz:n lisäsuodatuksen ennen kulmanopeus- ja teholaskentaa; sen voi poistaa arvolla `--cmj-kinematic-filter-hz 0`. Kaikki käytetyt asetukset, lähdekanavat, seisontajakso ja tapahtuma-ajat tallentuvat JSON-tiedostoon.

PDF:n ja HTML-esikatselun rinnalle tallentuvat samalla nimirungolla `_summary.csv`, `_joints.csv`, `_events.csv`, `_force_curves.csv`, `_raw_event_curves.csv`, `_joint_curves.csv` ja `_analysis.json`. PDF ja HTML-kuvaajat toimivat ilman verkkoyhteyttä. Mittauspäivä haetaan ensin trialin omasta ENF-metatiedosta; ilman sitä käytetään käytetyn lähdetiedoston muokkausaikaa (CMJ-perusraportissa CSV). `--measurement-date YYYY-MM-DD` antaa oikean päivän erikseen, jos tiedosto on kopioitu tai viety uudelleen.

```bat
env\python.exe -m app.cli data\kuura --protocol cmj --cmj-report performance --output reports\kuura_cmj.pdf --subject "Kuura"
```

## CMJ quick metrics Nexusissa

Lisää Nexusin pipelineen **Run Python Script** -operaatio ja valitse `app\nexus\cmj_quick_metrics.py` (absoluuttinen polku repositorioon). Myös tuttu `app\analysis\CMJ_quick_metrics_v3.py` käynnistää nyt saman laskennan. Trialin tulee olla avoinna, voimalevykanavien valmiita ja mukana pitää olla vakaa seisontajakso. Raakavoimalaskentaa varten sijoita operaatio ennen Nexusin suodatusta; operaatio itse ei suodata voimaa.

Nexus lukee voimalevyt 3+4 ja kirjoittaa CMJ-korkeuden, RSI-mod:n, impulssit, huippuvoiman, lähtönopeuden, time to take-offin, countermovement depthin ja vaiheiden kestot Analysis Parameters -kenttiin. Korkeus ja syvyys tallennetaan millimetreinä. Olemassa olevat arvot päivitetään. Voimalevyjen määritys näkyy alkuperäisen v3-tiedoston `FORCE_PLATE_NUMBERS`-asetuksessa; uuden käynnistystiedoston oletus on 3+4.

Nexusin SDK-luku ja parametrien kirjoitus tapahtuvat Nexusin omassa Pythonissa. Varsinainen laskenta ajetaan repositorion `env\python.exe`:llä, joten Nexusin Python-ympäristöön ei tarvitse asentaa SciPyä tai raportointikirjastoja. Luo ympäristö `SETUP_jumputils.bat`:lla. Tarvittaessa `JUMPUTILS_PYTHON` määrittää toisen yhteensopivan Pythonin. Massa haetaan valinnaisesta, urheilijaan yksiselitteisesti liittyvästä `.mp`-tiedostosta, sitten Nexusin subjektiparametrista ja lopuksi seisontavoimasta. Yli 5 % ristiriita kuormaan pysäyttää analyysin.

Hyppykorkeus on molemmissa työnkuluissa lähtönopeuteen perustuva COM:n nousu **irtoamisesta lennon huippuun**, `v_takeoff²/(2g)`. Se ei sisällä seisonta-asennosta irtoamisasentoon tulevaa COM-nousua. Oikea koko kehon COM:n `apex − COM at foot-off` mittaa samaa korkeutta ja voi toimia liikeanalyysin vertailuna; pelvis-segmentti ei sellaisenaan ole koko kehon COM.

Laskennan määritelmät, oletukset, tutkimusperusta ja jatkokehityksen rajapinnat: [docs/CMJ.md](docs/CMJ.md).
