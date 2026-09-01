# Jumputils

Jumputils muodostaa Drop Jump -HTML-raportteja toisiaan vastaavista C3D- ja Nexus-voimalevy-CSV-tiedostoista.

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
|   |   `-- cmj.py              Valmis laajennuspaikka CMJ:lle
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

Valitse mittauskansio, kirjoita mitattavan nimi ja paina **Create report**. HTML-raportti ja sitä tukevat CSV-tiedostot tallennetaan `reports`-kansioon.

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

CMJ-moduuli on tarkoituksella vain laajennuspaikka. CMJ-laskentaa ei ole aktivoitu ennen laboratorion tiedostonimien, kontaktitapahtumien ja raportoitavien suureiden määrittelyä.
