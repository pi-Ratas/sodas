# Sodas

*[English](README.md)*

**Sodas** – programa kalbininkams: ji sudeda viešus lingvistinius duomenynus (Glottolog, Concepticon, IE-CoR, CLICS, WALS ir kt.)
į vieną Neo4j grafą ir leidžia jį tyrinėti naršyklėje.

- **Žemė** – duomenynai, iš kurių auga sodai: jų atsisiuntimas ir importas į Neo4j; **LKEŽDB** (nebūtina) – Lietuvių kalbos
  etimologinio žodyno duomenų bazės žodžių aiškinimas kalbos modeliu.
- **Sodas** – grafo tyrinėjimas: paieška, mazgų ir ryšių „sodinimas“, tapačių mazgų apjungimas, pluoštai, trumpiausi keliai,
  žemėlapis, tyrimo krepšys, savi ryšiai (Ctrl+J); sodo atsisiuntimas (SVG, PNG, JSON) kartu su bibliografija.
- **Vaiva** – tyrimai su krepšio mazgais: formų garsinio panašumo klasterizacija, kalbų leksinis artumas ir genealoginis medis,
  sąvokų semantinis pastovumas; **dirbtuvės** – savo tyrimą galima sudėlioti iš detalių.
- **Bibliografija** – kiekvienas sodas ir tyrimas įsimena, kokius duomenynus naudojo; 📚 parodo jų ir Sodo citavimo įrašus
  (BibTeX, BibLaTeX, RIS, CSL-JSON, APA).

Programa veikia jūsų kompiuteryje: ji paleidžia nedidelį vietinį serverį, o dirbate naršyklėje adresu `http://127.0.0.1:8765/`.
Sąsaja yra 15 kalbų (kalbą keičia mygtukas viršuje dešinėje). Pirmą kartą atėjusiam į sodą pasiūloma trumpa pamoka
(ją bet kada pradėsite spustelėję ženklą SODAS viršuje kairėje).

---

## Ko reikia

| | |
|---|---|
| Operacinė sistema | Linux, macOS arba Windows 10/11 (programa kurta ir išbandyta Linux) |
| Python | 3.10 ar naujesnis |
| Neo4j | 5 ar naujesnė (Community – nemokama; papildinių nereikia) |
| Atmintis (RAM) | 8 GB pakanka keliems duomenynams; visiems 14 (ypač CLICS4) – 32 GB ar daugiau |
| Vieta diske | ~1,5 GB duomenynams; importo tarpinėms byloms (`build/`) ir Neo4j bazei – iki kelių dešimčių GB, kai importuojami visi |
| Internetas | duomenynams atsisiųsti (vieną kartą) ir žemėlapio plytelėms |

---

## Diegimas

### 1. Neo4j

Neo4j – grafų duomenų bazė, kurioje Sodas laiko duomenis.

- **Paprasčiausia (visos sistemos):** [Neo4j Desktop](https://neo4j.com/download/). Įdiekite, sukurkite naują vietinę
  duomenų bazę (*Local DBMS*), sugalvokite slaptažodį ir paspauskite **Start**.
- **Linux be grafinės aplinkos:** [Neo4j Community Server](https://neo4j.com/docs/operations-manual/current/installation/linux/)
  (`apt`/`dnf` paketas). Pirmą kartą nustatykite slaptažodį: `sudo neo4j-admin dbms set-initial-password <slaptažodis>`,
  tada `sudo systemctl start neo4j`.
- **Docker:**
  ```bash
  docker run -d --name sodas-neo4j -p 7474:7474 -p 7687:7687 -e NEO4J_AUTH=neo4j/<slaptažodis> neo4j:5
  ```

Patikrinti galima naršyklėje: <http://localhost:7474> turi atsiverti Neo4j Browser.

Jei importuosite daug duomenynų, Neo4j nustatymuose (`neo4j.conf`, Desktop – *Settings*) verta padidinti atmintį, pvz.
`server.memory.heap.max_size=4G`, `server.memory.pagecache.size=4G`.

### 2. Python

- **Linux:** dažniausiai jau įdiegtas; Debian/Ubuntu dar reikia `sudo apt install python3-venv`.
- **macOS:** `brew install python` arba iš [python.org](https://www.python.org/downloads/).
- **Windows:** iš [python.org](https://www.python.org/downloads/); diegiant pažymėkite **„Add python.exe to PATH“**.

### 3. Sodas

Atsisiųskite programą: GitHub puslapyje **Code → Download ZIP** (ir išskleiskite) arba su `git`:

```bash
git clone https://github.com/pi-Ratas/sodas.git
cd sodas
```

Sukurkite Python aplinką ir įdiekite Sodą:

**Linux / macOS**
```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -e '.[neo4j,vaiva]'
```

**Windows (PowerShell)**
```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
py -m pip install -e ".[neo4j,vaiva]"
```

(Jei PowerShell neleidžia paleisti `Activate.ps1`: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.)

### 4. Prisijungimas prie Neo4j

Nukopijuokite `neo4j.example.yaml` į `neo4j.yaml` ir įrašykite savo Neo4j slaptažodį:

```yaml
neo4j:
  uri: bolt://localhost:7687
  user: neo4j
  password: <jūsų slaptažodis>
  database: neo4j
```

`neo4j.yaml` į git nepatenka. Vietoje bylos galima naudoti aplinkos kintamuosius `KALBA_NEO4J_URI`, `KALBA_NEO4J_USER`,
`KALBA_NEO4J_PASSWORD`, `KALBA_NEO4J_DATABASE`.

### 5. Paleidimas

Iš Sodo aplanko (su įjungta `.venv`):

```bash
sodas
```

Atsidaro naršyklė (`http://127.0.0.1:8765/`). Sustabdyti – `Ctrl+C` terminale. Kitą kartą užtenka:
`cd sodas`, `source .venv/bin/activate` (Windows: `.venv\Scripts\Activate.ps1`), `sodas`.

Programos nustatymai, sodai, įkelti paveiksliukai, sode nubrėžtų ryšių sąrašas, Vaivos tyrimai ir žurnalas saugomi aplanke
`sodas-duomenys/` (atsarginei kopijai užtenka nukopijuoti jį ir Neo4j bazę).

---

## Duomenynai: atsisiuntimas ir apdorojimas

Duomenynai su programa **nepateikiami** – kiekvienas atsisiunčia juos pats. Sodas žino, kurią kiekvieno duomenyno versiją
siųstis: tą, su kuria programa išbandyta (GitHub archyvas, `git` nereikia).

1. Viršutinėje juostoje spauskite **Žemė** (skirtukas „Duomenynai“).
2. **⭳ Atsisiųsti visus trūkstamus** (~1,3 GB) arba **⭳ Atsisiųsti** prie pasirinktų. Eiga matoma apačioje kairėje.
   Duomenynai išskleidžiami į aplanką `duomenynai/`.
3. Pažymėkite duomenynus ir spauskite **Importuoti pažymėtus**. Importuojama nustatyta eile; jei pažymėtam duomenynui
   reikia autoriteto (Glottolog, Concepticon), programa jį pasiūlys pažymėti.
4. Po importo – **Susieti su autoritetais**.
5. Grįžkite į **Sodas** ir ieškokite (pvz. *Lithuanian*, *moon*).

**Pradžiai rekomenduojama:** Glottolog, Concepticon, CLTS ir IE-CoR – užtenka visiems Vaivos tyrimams, išskyrus semantinį
pastovumą (jam dar reikia DatSemShift). Mažesnė apimtis, greitas importas.

Tą patį galima padaryti komandine eilute:

```bash
kalba-import download --list                                  # duomenynai, versijos, licencijos, dydžiai
kalba-import download --only glottolog,concepticon,clts,iecor # atsisiųsti
kalba-import import-all --config datasets.yaml --only glottolog,concepticon,clts,iecor
kalba-import resolve
```

Kur atsisiųsti ir iš kur importuoti, nurodo `datasets.yaml` (santykiniai keliai). Jei turite savo duomenyno kopiją
(pvz. `git clone`), tiesiog nurodykite jos kelią – atsisiųsti nebereikės.

### Duomenynų licencijos

Duomenys nėra Sodo dalis ir turi savo licencijas. Naudodami juos tyrime, cituokite duomenynus (nuorodos – „šaltinis ↗“
prie kiekvieno duomenyno).

| Duomenynas | Versija | Licencija |
|---|---|---|
| Glottolog | v5.3 | CC BY 4.0 |
| Concepticon | v3.4.0 | CC BY 4.0 |
| CLTS | v2.3.0 | CC BY 4.0 |
| IE-CoR | v1.2 | CC BY 4.0 |
| WOLD | v4.2 | CC BY 4.0 |
| Lexibank (analysed) | v2.2.6 | CC BY 4.0 |
| CLICS4 | v1.0 | CC BY 4.0 |
| NoRaRe | v1.1 | **CC BY-NC 4.0** (ne komerciniam naudojimui) |
| PHOIBLE | v2.0.1 | CC BY 4.0 |
| WALS | v2020.5 | CC BY 4.0 |
| Grambank | v1.0.3 | CC BY 4.0 |
| D-PLACE | v3.2.0 | **CC BY-NC 4.0** (ne komerciniam naudojimui) |
| ASJP | v21.1 | CC BY 4.0 |
| DatSemShift | v1.1rc | CC BY 4.0 |

---

## LKEŽDB (nebūtina)

Skirtukas **Žemė → LKEŽDB** aiškina Lietuvių kalbos etimologinio žodyno duomenų bazės žodžius kalbos modeliu ir įtraukia juos į grafą.
Jai reikia LKEŽDB duomenų talpyklos `duomenynai/lkezdb/puslapiai.db`, kuri **su programa nepateikiama**, ir OpenAI
(ar suderinamo) API rakto – žr. [docs/OpenAI_raktas.md](docs/OpenAI_raktas.md). Be jų ši skiltis tiesiog neveikia,
visa kita veikia.

---

## Dažnos bėdos

- **„Neo4j nepasiekiamas“ / „slaptažodis nenurodytas“** – ar Neo4j paleista (<http://localhost:7474>)? Ar `neo4j.yaml`
  yra Sodo aplanke ir slaptažodis teisingas? `sodas` reikia leisti iš Sodo aplanko.
- **Atsisiuntimas nutrūko** – spauskite dar kartą; nebaigtas atsisiuntimas aplanko nepalieka.
- **Importas nutrūko dėl atminties** – importuokite po vieną duomenyną; didžiausias – CLICS4. Padidinkite Neo4j atmintį.
- **Prievadas 8765 užimtas** – `sodas --port 8780`.

Išsamus kiekvienos dalies aprašas – [docs/vadovas.md](docs/vadovas.md).

## Atnaujinimas

```bash
cd sodas
git pull                     # arba atsisiųskite naują ZIP
source .venv/bin/activate
python3 -m pip install -e '.[neo4j,vaiva]'
```

## Licencija ir citavimas

© 2026 Kęstutis Račkaitis. Programos kodas platinamas pagal **GNU Affero General Public License v3.0** ([LICENSE](LICENSE)):
jį galima laisvai naudoti, keisti ir platinti, bet pakeistos versijos (taip pat ir paleistos kaip tinklo paslauga) turi likti
atviros pagal tą pačią licenciją.

Programoje yra trečiųjų šalių bibliotekų: [Cytoscape.js](https://js.cytoscape.org/) (MIT),
[Leaflet](https://leafletjs.com/) (BSD-2-Clause); vėliavų paveiksliukai – [flag-icons](https://github.com/lipis/flag-icons) (MIT).

Jei Sodas pravertė jūsų tyrime, cituokite jį ([CITATION.cff](CITATION.cff); GitHub – „Cite this repository“). Programoje
citavimo įrašą rasite spustelėję ženklą SODAS, o sodo ar tyrimo bibliografiją (Sodas ir visi naudoti duomenynai) – mygtuku 📚.
Lange „Apie Sodą“ rodomi autoriaus kontaktai iš `kontaktai.yaml`.
