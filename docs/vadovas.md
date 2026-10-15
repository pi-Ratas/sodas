# Sodas: išsamus vadovas

Diegimas aprašytas [README.lt.md](../README.lt.md). Čia – importo komandos, kiekvienos programos dalies (Sodo, Vaivos, LKEŽDB, Duomenynų) aprašas ir techninės smulkmenos.

## Importuotojas

Įdiegimas iš šio katalogo:

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -e .
python3 -m pip install -e '.[neo4j]'   # tik apply komandai
python3 -m pip install -e '.[vaiva]'   # numpy – Vaivos spektrinei analizei
```

CLI komandos:

```bash
kalba-import inspect --dataset iecor --path duomenynai/iecor
kalba-import plan --dataset iecor --path duomenynai/iecor
kalba-import emit --dataset iecor --path duomenynai/iecor --out build/iecor
kalba-import apply --emit-dir build/iecor --uri bolt://localhost:7687 --user neo4j --password slapta
kalba-import verify --emit-dir build/iecor --strict
kalba-import resolve
kalba-import ui
kalba-import candidate-add --emit-dir build/iecor --left-label Form --left-key 'iecor:form:1' --right-label Form --right-key 'iecor:form:2' --reason 'kuratoriaus pastaba' --rule-id curated-v1 --evidence-json '{"record_keys":["..."]}'
```

`plan` ir `emit` Neo4j serverio nereikalauja. `emit` sukuria:

- `constraints.cypher`
- `node_*.cypher` ir `rel_*.cypher`
- `*.ndjson` parametrų partijas
- `manifest.json`

CLDF/CSVW skaitytuvas yra lokalus ir ribotas, bet jis taiko metaduomenis: lentelių vaidmenys imami iš `dc:conformsTo`, CLDF stulpeliai iš `propertyUrl`, FK iš `foreignKeys`, o reikšmėms taikomi CSVW `separator`, `null`, `dialect` ir sudėtiniai PK. Pilnos `pycldf` validacijos jis nepakeičia; schema ir neįtraukti galimi duomenų failai rodomi `inspect` rezultato `file_inventory`.

Vidiniai FK tame pačiame leidime sprendžiami prieš rašymą į Neo4j. Išspręstos nuorodos virsta `SourceRecord-[:REFERS_TO_RECORD]->SourceRecord`; nerastos ar dviprasmės lieka `RawReference` su diagnostika. Tai nepriklauso nuo Glottolog, Concepticon ar kitų autoritetų įkėlimo.

Automatinis `POSSIBLE_IDENTITY` generavimas tarp leksinių duomenynų išjungtas. Pagrįstus kandidatus galima pridėti su `candidate-add`; komanda prideda `IdentityCandidate`, `Evidence`, kandidato galus ir `POSSIBLE_IDENTITY` ryšį prie emit manifesto.

Kontraktas `kalba-neo4j/1.1` kuria žmogui skaitomą tyrimo grafą: semantiniai mazgai gauna `display_name`, `dataset`, `dataset_release`, `source_record_key` ir `search_*` laukus, o paprasti prasminiai faktai rašomi tiesioginiais ryšiais, pvz. `HAS_FORM`, `USED_IN`, `DENOTES`, `COGNATE_IN`.

Palaikomi profilių `dataset_id`: `clts`, `phoible`, `wals`, `clics4`, `concepticon`, `norare`, `dplace`, `glottolog`, `grambank`, `lexibank_analysed`, `iecor`, `wold`, `asjp`, `datsemshift`.

Profilį galima pakeisti:

```bash
kalba-import inspect --dataset iecor --path duomenynai/iecor --profile kalba_import/profiles/iecor.yaml
```

Testai be Neo4j:

```bash
python3 -m unittest discover -s tests
```

Neo4j testavimas ranka:

```bash
kalba-import emit --dataset iecor --path duomenynai/iecor --out /tmp/kalba-iecor --batch-size 500
kalba-import apply --emit-dir /tmp/kalba-iecor --uri bolt://localhost:7687 --user neo4j --password '<slaptažodis>'
kalba-import verify --emit-dir /tmp/kalba-iecor --strict
```

## Programa „Sodas“: Žemė, Sodas, Vaiva, nustatymai

```bash
source .venv/bin/activate
sodas                      # atidaro http://127.0.0.1:8765/  (tas pats: kalba-import ui)
```

Viršutinėje juostoje – trys skyriai: **Žemė** (`/zeme`: duomenynai ir LKEŽDB), **Sodas** (`/`), **Vaiva** (`/vaiva`). Dešinėje – sąsajos kalba ir **⚙ nustatymai** (`/nustatymai`). Grįžus į sodą rodomas tas pats sodas, su kuriuo dirbta šioje kortelėje. Seni adresai `/importas`, `/lkezdb` ir `/nustatymai?skiltis=duomenynai|lkezdb` nukreipia į Žemę.

Programa skirta vienam žmogui jo kompiuteryje: prisijungti nereikia, visi sodai, nustatymai ir tyrimai – jo. Viskas, ką programa įsimena, laikoma aplanke `sodas-duomenys/`:

| Byla | Kas joje |
|---|---|
| `settings.json` | nustatymai (tema, mazgų ir ryšių išvaizda, savybių paveiksliukai, ribos, išjungti duomenynai) |
| `gardens/<id>.json` | sodai (kiekvienas – su naudotų duomenynų sąrašu bibliografijai) |
| `images/` | įkelti paveiksliukai ir vėliavos |
| `rysiai.json` | sode nubrėžtų ryšių sąrašas (patys ryšiai – Neo4j) |
| `juodrasciai.json` | Vaivos dirbtuvių drobės juodraštis |
| `vaiva/<id>.json` | atlikti Vaivos tyrimai |
| `zurnalas.jsonl` | programos klaidos ir įspėjimai (⚙ → Žurnalas) |

Kad perkeltumėte darbą į kitą kompiuterį, nukopijuokite `sodas-duomenys/` ir Neo4j bazę (`neo4j-admin database dump`).

**Kalba ir istorija.** Sąsaja yra lietuvių, anglų, latvių, lenkų, ukrainiečių, baltarusių, rusų, vokiečių, prancūzų, ispanų, italų, portugalų, arabų, japonų ir kinų kalbomis. Iš pradžių kalba parenkama pagal šalį (naršyklės laiko juostą), kitaip – pagal naršyklės kalbą, o jei programa jos nemoka – angliškai; mygtuku juostos dešinėje (pvz. „LT“) kalbą bet kada galima pakeisti (pasirinkimas įsimenamas). Juostos kairėje ← → – atgal ir pirmyn: perėjus iš vieno sodo į kitą, ← grąžina į ankstesnį.

Vertimai – `kalba_sodas/i18n/`: `raktai.tsv` (numeris → lietuviškas tekstas) ir `en.tsv`, `lv.tsv`, `pl.tsv`, `uk.tsv`, `be.tsv`, `ru.tsv`, `de.tsv`, `fr.tsv`, `es.tsv`, `it.tsv`, `pt.tsv`, `ar.tsv`, `ja.tsv`, `zh.tsv` (numeris → vertimas; `{0}`, `{1}` – programos įterpiamos reikšmės, jas reikia palikti). Pridėjus ar pakeitus tekstus kode:

```bash
python -m kalba_sodas.i18n.istraukti                # naujiems tekstams – nauji numeriai, kiek ko neišversta
python -m kalba_sodas.i18n.istraukti --trukstami en # neišversti angliški (numeris<TAB>tekstas)
```

Neišverstas tekstas rodomas lietuviškai; serveris pakeistus žodynus naudoja be perkrovimo.

**Kuo remtasi ir kaip cituoti.** Kiekvienas sodas ir kiekvienas Vaivos tyrimas atskirai seka, kokius duomenynus naudojo (`kalba_sodas/sekimas.py`): sodas – iš jame buvusių mazgų ir ryšių (kartą naudotas duomenynas lieka sąraše, net jei mazgai vėliau pašalinti), tyrimas – iš to, ką jo užklausos perskaitė (ir ką tyrimas ar dirbtuvių detalė skaito iš bylų, pvz. CLTS). Įrašoma ir duomenyno versija (git žyma, pvz. IE-CoR `v1.2`), pirmo ir paskutinio naudojimo data. Mygtukas **📚** (sodo įrankių juostoje, „Tvarkyti sodus“ eilutėse, Vaivos tyrimo antraštėje) atveria meniu: **BibTeX, BibLaTeX, RIS** (EndNote, Zotero, Mendeley), **CSL-JSON** (Zotero, Mendeley, Pandoc), **Tekstas (APA)**. Bibliografijoje – SODAS įrašas (DOI, saugykla, versija) ir kiekvieno naudoto duomenyno įrašas taip, kaip prašo jo autoriai (`kalba_sodas/bibliografija.py`, `CATALOGUE`); duomenynas be katalogo įrašo cituojamas pagal jo aplanko `.zenodo.json` / `metadata.json`. Galima nukopijuoti arba atsisiųsti bylą.

Sodo įrašas imamas iš **`CITATION.cff`** (Citation File Format) šalia `datasets.yaml`, o jei ten jos nėra – iš programos aplanko (ji pateikiama su programa). Jei bylos visai nėra, pateikiamas **preliminarus** įrašas (pažymėtas „RUOŠIAMA“). Byla skaitoma iš naujo jai pasikeitus – perkrauti nereikia.

**Dalijimasis sodais.** Sodo sąraše (▾ šalia pavadinimo) ir ⚙ → Tvarkyti sodus: **⬇ Atsisiųsti šį sodą (JSON)** – byla `<pavadinimas>.sodas.json` (formatas `sodo-byla/1`: mazgai, ryšiai, vaizdas, krepšys ir naudotų duomenynų sąrašas); **⬆ Įkelti sodą iš bylos…** – kieno nors atsiųstas sodas tampa nauju jūsų sodu, o naudotų duomenynų sąrašas ateina kartu, tad ir bibliografija lieka teisinga.

### Žemė (`/zeme`)

Skirtukai **Duomenynai** (atsisiuntimas, importas, susiejimas su autoritetais, trynimas) ir **LKEŽDB**.

### Sodas

- Sodo pavadinimo laukas kartu yra sodų sąrašas: įėjus į jį atsiranda kiti sodai (atidaryti čia arba su Ctrl naujoje kortelėje), naujo sodo kūrimas ir „Tvarkyti sodus“; rašant keičiamas šio sodo pavadinimas.
- Įrankių juostos mygtukai – tik ženklai (pavadinimas – užvedus pelę). 👁 **Rodinys**: mazgų ir ryšių pavadinimų jungikliai (Ctrl+Shift+1 / Ctrl+Alt+1) ir sode esantys mazgų bei ryšių tipai su kiekiais – nuėmus varnelę tipas paslepiamas. **Atsisiųsti** (rodyklė žemyn): SVG (vektorinis vaizdas), PNG (paveikslas, dvigubo ryškumo) arba JSON (sodo byla `sodo-byla/1`, vėl įkeliama „Tvarkyti sodus“); be žemėlapio – visas sodas, su žemėlapiu – matomas vaizdas. **Kiekvienoje byloje – visa bibliografija** (SODAS ir visi sode – ir rodomame žemėlapyje – naudoti duomenynai): SVG ir PNG apačioje rodo cituotinų šaltinių sąrašą (APA) ir laiko jį metaduomenyse (SVG `<metadata>`: APA, BibTeX, RIS; PNG `iTXt`: Description – APA, Comment – BibTeX), JSON byla turi lauką `bibliografija` (APA, BibTeX, RIS, CSL-JSON). Be bibliografijos atsisiųsti negalima.
- Kelio mygtukas ⇝ matomas tik kai pažymėti lygiai du mazgai.
- Paliesti (pačiupinėti) mazgai – pažymėti, tempti, išskleisti ar pridėti iš paieškos – rodomi ryškiau ir su žiedu. Slepiant mazgo ryšių tipą paliesti kaimynai ir ryšiai su jais lieka.
- Vidurinis pelės klavišas ant mazgo – to mazgo skydelis (išskleisti, ryšiai pagal tipą su „rodyti“ / „slėpti“, paslėpti, paliestas, tipo spalva ir forma); ant ryšio – bekelė, slėpti tipą, to tipo linijos išvaizda.
- Shift + tempimas – pažymėti stačiakampiu; H – paslėpti pažymėtus, Shift+H – parodyti paslėptus.
- Paieška viršuje (Ctrl+F): radiniai grupuojami pagal tipą, rodomi pirmieji su „rodyti daugiau“. Jei sodas tuščias, po ~2,5 s radiniai laikinai parodomi sode; pasirinkus vieną, kiti po kelių sekundžių dingsta.
- Dešinys pelės klavišas ant mazgo: „Rodyk viską“, „Rodyk svarbiausia“, „Išskleisk“, „Pridėk į krepšį“, „Paslėpk“ ir kt.; ant ryšio – „Bekelė“; fone – „Rodyti paslėptus“. Prie kiekvieno nurodymo – jo ženkliukas (tie patys kaip įrankių juostoje). Dukart spustelėjus – išskleisti.
- Išskirtą apjungtą mazgą (pvz. `Languoid` iš IE-CoR ir Glottolog, ženkliukas ⧉) vėl sujungia meniu punktas „Apjungti tapačius“ (su tuo pačiu ženkliuku); fone – „Apjungti visus tapačius“. Vienodų pavadinimų mazgus (×N) – „Sujunk vienodus“.
- **Drąsiai jungti mazgus** (⚙ → Ribos ir dydžiai, numatyta įjungta): to paties pavadinimo ir tos pačios kalbos (pagal Glottolog kodą, kitaip – kalbos pavadinimą) formos ir lytys (`Form`, `Lexeme`) iš visų duomenynų rodomos kaip vienas mazgas, pvz. „mèsti“ iš IE-CoR ir Lexibank. „Rodyti atskirai“ išskiria; vėl įjungus varnelę – sujungiama iš naujo. Žemėlapyje jie rodomi atskirai.
- Užvedus pelę ant vėliavos (ar kito savybės paveiksliuko) prie mazgo, parodoma, ką ji reiškia: šalį ar vietovę ir kalbą, pvz. „Lietuva · Lithuanian (kalba)“.
- Iš vieno mazgo rodoma ne daugiau kaip nustatyta kaimynų pavadinimų (numatyta 50): to paties pavadinimo kaimynai sode apjungiami į vieną mazgą („rain ×12“), todėl įkeliami visi kartu ir skaičiuojami kaip vienas (dideli – kaip pluoštas, žr. toliau). Likusieji – „+N TIPAS“ mazgas, kurį spustelėjus įkeliama daugiau; N skaičiuojamas pagal tai, kas jau yra sode, todėl pakartotinai išskleidus ženkliukas nebeatsiranda, jei visi ryšiai jau rodomi. Bendros ribos: 200 mazgų, 600 ryšių (keičiama nustatymuose).
- Tyrimo krepšys: mygtukas 🧺 sudeda į krepšį pažymėtus mazgus, o jei nieko nepažymėta – parodo krepšio turinį; rodyklėlė ▾ šalia jo – „Rodyti krepšį“, „Pridėti prie krepšio“, „Išvalyti krepšį“. Naujas sodas (＋, „Į atskirą sodą“) prasideda tuščiu krepšiu.
- Trumpiausi keliai tarp dviejų mazgų (visi to paties ilgio): kelio ilgis neribojamas – visuomet ieškoma trumpiausio. „Bekelė“ pašalina ryšio tipą iš kelio paieškos (jei paieška per plati ir užtrunka, Neo4j ją nutraukia po 30 s – tada padeda bekelės).
- **Ctrl+J** (arba meniu „Sukurti ryšį“, kai pažymėti du mazgai) – naujas ryšys tarp **bet kokių** dviejų mazgų. Ryšio pavadinimą galima pasirinkti iš sąrašo arba įrašyti: sąraše – duomenų bazės ryšių tipai ir anksčiau sugalvoti savi pavadinimai. Duomenų bazės tipas naudojamas toks, koks yra; bet koks kitas pavadinimas tampa ryšiu **`CUSTOM`** su savybe `label` – sode rodomas tas užrašas, o ryšių tipų sąrašas neprišiukšlinamas.
- Ryšys iškart įrašomas į Neo4j (duomenynas **„Papildymai“**, raktas `sodas-rysys:<nr.>`) ir matomas kaip visi kiti – išskleidus mazgą, kelių paieškoje. Jų sąrašas – ⚙ → **Mano ryšiai** (programa jį laiko `sodas-duomenys/rysiai.json`, kad nereikėtų perskaityti visų Neo4j ryšių): „Rodyti sode“ atneša abu mazgus su ryšiu į šį sodą, „Ištrinti“ – pašalina iš Neo4j. Spustelėjus ryšį sode – kada jis nubrėžtas, pastaba ir „Ištrinti ryšį“. (Anksčiau sode nubrėžtų ryšių duomenynas vadinosi „kuratorius“ – pirmą kartą paleidžiant programą jie pervadinami; tai perskaito visus Neo4j ryšius, todėl daroma tik kartą.)
- **Pluoštai.** Jei vieno pavadinimo kaimynų daug (numatyta – 21 ir daugiau; ⚙ → Ribos ir dydžiai → „Pluoštas nuo“; virš 1000 – visada), serveris jų neatsiunčia po vieną: sode atsiranda vienas mazgas „skin ×10963“ su tikru skaičiumi. Todėl nebelieka „+N“ mazgų, kurie tik padidintų apjungto mazgo skaičių, o sodas neapsikrauna. Pluošto skydelyje – jo ryšiai pagal tipą ir mazgų sąrašas (po 50, su kalbomis; „＋“ įkelia vieną į sodą); „Rodyti atskirai“ (iki 200) įkelia visus. Išskleidus pluoštą, serveris parodo visų jo mazgų kaimynus (vienodi vėl apjungiami). Pluoštas išsaugomas su sodu. Jei sode jau buvo to paties pavadinimo mazgų, kurių niekas kitas nelaiko (nepaliesti, ne krepšyje, be kitų ryšių), jie įeina į pluoštą.
- **Žemėlapis pagal pažymėtą mazgą** (🗺). Pažymėtas `Sense` (paprastas, apjungtas ×N ar pluoštas) – žemėlapyje jo lemos (`Lexeme` per `HAS_SENSE`; jei lemos nėra, kaip LKEŽDB, – jo lytys `Form`). **Ctrl + 🗺** su `Sense` – visos jo sąvokos lytys: nuo `Sense` per `DENOTES` į `Concept`, iš ten į tą pačią sąvoką kituose duomenynuose (`CORRESPONDS_TO`), visi tos sąvokos `Sense` ir jų lytys. Pažymėtas `Concept` – visų tos sąvokos (ir tos pačios sąvokos kituose duomenynuose) `Sense` lemos (`Sense` be lemos – jo lytys). Pažymėtas `CognateSet` – visos jo lytys (`COGNATE_IN`). Kitas apjungtas mazgas (×N) su Ctrl ar pluoštas – visi jo mazgai. Tą patį siūlo ir dešiniojo klavišo meniu („Lemos žemėlapyje“, „Visos sąvokos lytys žemėlapyje“, „Sąvokos lemos žemėlapyje“, „Lytys žemėlapyje“). Serveris mazgus randa visus, ne tik įkeltus į sodą. Vienu metu piešiama ne daugiau kaip 400 mazgų, tolygiai paskirstytų matomoje žemėlapio dalyje; artinant rodomi tos srities mazgai (apačioje parašyta, kiek rodoma iš kiek). Sodas tuo metu tik paslėptas, todėl išjungus žemėlapį (🗺) jis iškart grįžta toks, koks buvo (šis vaizdas neišsaugomas).
- **Rankinis apjungimas.** Pažymėjus du ar daugiau mazgų (Shift + spustelėjimas), dešiniojo klavišo meniu – „Apjungti pažymėtus“. Jei pavadinimai skiriasi, paklausiama, kurį rodyti, arba galima įrašyti savą. Toks mazgas yra tik šio sodo (išsaugomas su sodu, į duomenų bazę nerašomas); jį galima pervadinti ir vėl išskirti („Rodyti atskirai“). Visi apjungti mazgai (tapatūs, drąsiai ir rankiniu būdu apjungti) turi ženkliuką ⧉, to paties pavadinimo grupės (×N) – sluoksnių ženkliuką; spustelėjus jį – „Išskirti“ / „Rodyti atskirai“.
- Išskleidžiant LKEŽDB žodį (`Entry`), kurio straipsniai dar neįtraukti į Neo4j, atsidaro Žemė → LKEŽDB ties tuo žodžiu su pranešimu, kad jį galima išaiškinti kalbos modeliu.
- Atidarant sodą mazgų pavadinimai ir savybės atnaujinami iš Neo4j (sodas saugo jų kopiją).
- **⚙ → Duomenynai**: kiekvieną duomenyną galima išjungti ir vėl įjungti (jungtukas, ne įkėlimas iš naujo). Išjungto duomenyno mazgų serveris neieško, neišskleidžia, nerodo keliuose ir žemėlapyje; sode esantys paslepiami ir, įjungus, iškart grįžta. Būsenos eilutė apačioje rodo, kiek duomenynų išjungta (spustelėjus – į nustatymus).
- Jei užklausa ar darbas trunka ilgiau nei 2 s, viršuje rodoma „Puslapis dirba…“ su sekundėmis.
- Kiekviena naršyklės kortelė gali turėti savo sodą; sodai išsaugomi automatiškai. Paslėpti mazgų ir ryšių tipai galioja tik tame sode: naujas sodas ir „Į atskirą sodą“ prasideda su visais tipais matomais. Nustatymuose „Tvarkyti sodus“ – pervadinti, kurti kopijas, atsisiųsti, trinti.
- **Pamokos.** Pirmą kartą atėjusiam į sodą po kelių sekundžių kampe pasiūloma trumpa sodo pamoka („Pradėti pamoką“ / „Ne dabar“; daugiau nesiūloma). Pamoka – 13 žingsnių: kiekvienas paryškina vieną sodo dalį (paieška, sodas, pelė, mazgo aprašas, 👁, 🗺, 🧺, atsisiuntimas, sodai, kitos dalys, kalba ir nustatymai, ženklas), antrasis kviečia susirasti ir pasodinti žodį (arba „Padaryk už mane“; paspaudus „Toliau“ su tuščiu sodu pavyzdys pasodinamas pats, nes kiti žingsniai kalba apie mazgus). Langelį galima tempti už antraštės – jis lieka ten, kur padėtas (↺ – grąžinti prie aiškinamos dalies). Esc – nutraukti, ← / → – atgal ir pirmyn. Pamoką bet kada galima pradėti per ženklą SODAS → „Pradėti sodo pamoką“; kitų puslapių pamokos ruošiamos (ten taip ir parašyta). Pamokos – `static/pamoka.js` (`LESSONS`), įkeliamos tik prireikus.
- **Programos ženklas ir „Apie Sodą“.** Viršutinės juostos pradžioje, prieš ←, – „Sodas“ ženklas. Jo spalvos imamos iš temos (⚙ → Tema → Spalvos po vieną → „Ženklas“; numatyta – paryškinimo spalva): raidės pereina iš ženklo spalvos į juostos spalvą, vienas lapelis – ženklo spalvos, kitas tamsesnis; ženkliukas O raidėje lieka savo spalvų. Spustelėjus atsiveria „Apie Sodą“: trumpas aprašymas, citavimas (iš `CITATION.cff`, „Kiti formatai…“ – BibTeX, RIS ir kt.), susisiekimo duomenys ir versija. **Susisiekimo duomenys rašomi į `kontaktai.yaml`** (šalia `datasets.yaml`, kitaip – programos aplanke); byla skaitoma iš naujo jai pasikeitus, tušti laukai nerodomi. Naršyklės kortelės paveiksliukas – `sOdas_ženkliukas.svg` (`static/ikonos/zenkliukas.svg`).
- Nustatymai (⚙): tema (šviesi / tamsi / pagal Saulę – numatyta; šviesios ir tamsios temos spalvos atskiros; „Kontrastas“ – kiek skiriasi fonas, skydeliai, žymės ir linijos; kiekvieną iš 14 spalvų galima parinkti ranka; pavyzdys ir kontrasto patikra rodo, kurios spalvos per panašios; temos perėjimas – 4 s), mazgų ir ryšių išvaizda, savybių paveiksliukai (tipas → savybė iš sąrašo → reikšmė iš sąrašo) ir išskaičiuotos savybės (numatyta `language` žodžiams), ribos ir mazgų dydis (varnelė „visi mazgai vienodo dydžio“ – apjungti mazgai ir tada lieka kiek didesni; kitaip dydis pagal matomų ar visų ryšių skaičių), sodų tvarkymas, trumpiniai, žurnalas.
- Pavyzdys: „Savybių paveiksliukai“ → taisyklė `Languoid · display_name · Lithuanian` su vėliavėle – vėliavėlė atsiras prie visų lietuviškų formų, leksemų ir reikšmių.
- „Savybių paveiksliukai“ → „🏳 Priskirti vėliavas kalboms“ (arba `sodas vėliavos`): kalboms su žinoma valstybės ar regiono vėliava (sąrašas pagal Glottolog kodą – `kalba_sodas/flags.py`) pridedamos taisyklės `Languoid · display_name · <pavadinimas>` visiems tos kalbos pavadinimams visuose duomenynuose. Vėliavos – [flag-icons](https://github.com/lipis/flag-icons) SVG (MIT), išsaugomos tarp sodo paveiksliukų; istorinės kalbos („Old …“, „Classical …“) vėliavų negauna, esamos taisyklės nekeičiamos.

Trumpiniai: Shift / Alt / Ctrl+Shift + pelės ratukas – mazgų dydis / mazgų ir ryšių užrašų dydis / ryšių storis; Shift+Home – visas sodas; Home – pažymėtas mazgas; Ctrl+F – paieška; F3 – kitas radinys; Ctrl+Shift+Numpad ± – didžiausias mazgas; Ctrl+Alt+Numpad ± – mažiausias mazgas; Ctrl+Alt+Shift+Numpad ± – savybių paveiksliukai; Ctrl+Numpad ± – raidžių dydis; Ctrl+J – ryšys tarp dviejų pažymėtų; Ctrl+Shift+1 / Ctrl+Alt+1 – mazgų / ryšių užrašai; H / Shift+H – paslėpti pažymėtus / parodyti paslėptus.

### Vaiva (`/vaiva`)

Vaiva (Vaivos dirbtuvės) kaupia spektrinės analizės tyrimus. Sode sudėkite mazgus į krepšį (dešinys klavišas → „Pridėk į krepšį“), atverkite **Vaiva**, pasirinkite tyrimą ir spauskite „Tirti“. Imamas šios kortelės sodo krepšys; tyrimui netinkami mazgai rodomi pilkai. „?“ prie kiekvieno parametro – ką jis reiškia ir kokios jo ribos. ＋ – naujas sodas (tuščias krepšys). Kiekvienas atliktas tyrimas išsaugomas (`sodas-duomenys/vaiva/<id>.json`) ir lieka sąraše kairėje; kiekvienas tyrimas turi savo vaisių vaizdavimą.

**Formų garsinio panašumo spektrinė klasterizacija.** Priima `Concept` (ir per `CORRESPONDS_TO` susietas sąvokas), `Sense`, `Lexeme`, `CognateSet` ar pačias `Form`; sąvokai formos randamos per `Sense → Lexeme → Form`.

1. Analizės segmentai (pirminiai duomenys neperrašomi): `Form.segments` (CLDF `Segments`) → IE-CoR `Phonemic_Segments` (iš formos `SourceRecord`) → duomenyno `etc/orthography.tsv` (ilgiausio atitikmens skaidymas; variantai `loir, loer` tiriami atskirai, atstumu laikomas mažiausias). Jei profilis nežino kurio nors ženklo, forma **neįtraukiama** ir parodoma su priežastimi; tarimas neišradinėjamas. Rekonstruotos (`*`) formos įtraukiamos tik pažymėjus parametrą.
2. Kiekvienas segmentas susiejamas su CLTS `Sound`: pirmiausia BIPA, tada kita CLTS sistema, tik jei ji vienareikšmė (garsų klasių sistemos, pvz. ASJP, nenaudojamos), tada apytiksliai be kirčio ir kitų diakritikų.
3. Atstumas: redagavimo atstumas, kur garso pakeitimas kainuoja skirtingų CLTS požymių dalį (0–1), įterpimas – 0,5, padalyta iš ilgesnės formos ilgio.
4. Spektrinė analizė (`numpy`): savaime derinamas Gauso branduolys (7 artimiausi), normalizuota Laplaso matrica, grupių skaičius pagal savųjų reikšmių tarpą (arba nurodytas), k-vidurkiai. Išdėstymas – klasikinis daugiamatis skalavimas.
5. Patikra po to: IE-CoR kognatai (ARI, grynumas, kaip kognatų grupės skyla) ir Glottolog šakos.

Vaisiai: garsinis sodas (formos išdėstytos pagal atstumus, spalvos ir numeriai – grupės; „Atverti sode“ sukuria naują sodą su šiomis vietomis ir spalvomis), savųjų reikšmių ir kokybės pagal k grafikai (spustelėjus k – perskaičiuojama), grupių kortelės, atstumų matrica, grupių × kognatų ir × šakų lentelės, visų formų, neįtrauktų formų ir CLTS garsų lentelės; prie kiekvienos išvados – trumpas paaiškinimas.

**Kalbų leksinis artumas ir genealoginis medis** (iš bandymo `laikina/spektras.py`). Krepšys nebūtinas: be jo tiriamos visos kalbos su kognatų duomenimis; Glottolog šeima ar šaka (pvz. Balto-Slavic) apriboja kalbas, sąvokos – reikšmes. Kiekvienai kalbų porai: leksinis artumas S = C/M (M – abiejose kalbose koduotos Concepticon reikšmės, C – kiek jų turi bendrą kognatų grupę; poros su M < riba nevertinamos) ir genealoginis atstumas Glottolog medyje – bendro protėvio gylis (numatyta) arba briaunų skaičius (kaip pirmajame bandyme). Toliau:

1. Spearman ρ ir Mantel permutacijų testas (ar ryšys ne atsitiktinis); abiejų matų palyginimas.
2. Artumas pagal atstumą medyje (dėžės kiekvienam atstumui).
3. Leksinio ir medžio grafų normalizuoto Laplaso spektrai, leksinės grupės (savųjų reikšmių tarpas) ir jų ARI su Glottolog šakomis kiekviename medžio lygyje.
4. Žemėlapiai pagal žodyną ir pagal medį (MDS arba savieji vektoriai), susieti užvedimu.
5. Leksinis medis (UPGMA): kurios šakos vientisos ir kas į jas įsiterpia; didžiausias skilimas.
6. Kiekvienos kalbos atitikimas medžiui (Goodman–Kruskal γ), netikėtos poros: skirtingų šakų, bet leksiškai artimos (galimi kontaktai) ir tos pačios šakos, bet tolimos.

Visų IE-CoR kalbų rezultatas: 156 kalbos, ρ = 0,55 (briaunų skaičius duoda tik 0,26), 4 leksinės grupės, labiausiai atitinkančios 2-ąjį Glottolog lygį (ARI 0,73), visos 9 kelių kalbų šakos leksiniame medyje vientisos.

**Sąvokų semantinis pastovumas.** Krepšys nebūtinas (tuščias – visas grafas); krepšio sąvokos paryškinamos ir aprašomos atskirai, Glottolog šaka apriboja IE-CoR kalbas. Formos ir reikšmės pastovumas matuojami atskirai, kiekvienas komponentas – atskirai (procentiliai, 100 % – pastoviausia):

- forma (IE-CoR + Glottolog): kognatų išlaikymas, išlikimas tolimose šakose, leksinio pakeitimo dažnis (Fitch parsimonija medyje);
- reikšmė: polisemija IE-CoR (tas pats žodis kelioms sąvokoms), polisemija DatSemShift (keliose šeimose), kaimynystės pastovumas (ar šeimos sieja su tomis pačiomis reikšmėmis), spektrinės padėties pastovumas (sąvokos vieta viso polisemijos tinklo Laplaso erdvėje, žiūrint iš kiekvienos šeimos).

Toliau: komponentų koreliacijos ir pagrindinės komponentės (ar pagrįsta jungti į vieną indeksą), Concepticon semantinių laukų permutacijų testai (ar grafas pats iškelia kūno dalis, giminystę, skaičius), forma × reikšmė kvadrantai. Visų 170 IE-CoR sąvokų rezultatas: formos komponentai tarpusavyje koreliuoja (ρ ≈ 0,72), su reikšmės komponentais – beveik ne (ρ ≈ 0,05); viena bendra kryptis paaiškina tik 35 %, todėl vieno indekso nedaroma; formos pastovumu reikšmingai išsiskiria skaičiai (Quantity).

#### Dirbtuvės: tyrimas iš detalių

Vaivos kairėje viršuje – du režimai: **Tyrimai** (trys aukščiau aprašyti tyrimai su savo vaizdavimu) ir **🔧 Dirbtuvės**. Dirbtuvėse tyrimas surenkamas iš detalių ant drobės:

- detalė iš sąrašo kairėje nutempiama į drobę (arba spustelima – tada ji pastatoma šalia pažymėtos ir prie jos prijungiama);
- jungiama tempiant nuo išėjimo taškelio (dešinėje) iki įėjimo (kairėje); taškelio spalva – duomenų tipas, tempiant paryškinami tik tinkami įėjimai, netinkama jungtis atmetama su paaiškinimu; nuo įėjimo nutempus esamą jungtį, ją galima perkelti;
- spustelėjus detalę, dešinėje – jos aprašas, parametrai su „?“, įėjimai ir išėjimai, o po tyrimo – kas gauta, kiek vienetų neįtraukta, klaida;
- drobė stumdoma tempiant tuščią vietą, mastelis – pelės ratukas; Delete – pašalinti detalę ar jungtį, Ctrl+Z / Ctrl+Y – atšaukti / grąžinti, Ctrl+D – kopija;
- „▶ Tirti“ siunčia sąranką serveriui; vaisiai rodomi skirtuke „🍎 Vaisiai“ ta tvarka, kuria vaisių detalės stovi drobėje (iš viršaus į apačią), apačioje – visi neįtraukti vienetai su priežastimi. Nepavykusi detalė kitų nesustabdo: drobėje ji raudona, nuo jos priklausančios – pilkos;
- sąranka išsaugoma su kiekvienu tyrimu (atvėrus tyrimą iš sąrašo, atsiveria ir jo sąranka), drobės juodraštis laikomas `sodas-duomenys/juodrasciai.json` ir laukia kito apsilankymo, „⬇ Atsisiųsti“ / „⬆ Įkelti“ – sąrankos failas (`.vaiva.json`) dalijimuisi;
- **Paruoštos sąrankos**: trys tyrimai, surinkti iš detalių (rezultatai sutampa su tyrimų), ir dvi naujos – „Garsiniai kalbų atstumai, medis ir geografija“, „Leksinis artumas ir geografija“.

Duomenų tipai: **Krepšys**, **Vienetai** (formos, kalbos, sąvokos su požymiais), **Atstumai**, **Panašumai**, **Grafas**, **Spektras**, **Skaidinys**, **Išdėstymas**, **Medis**, **Rodikliai**. Detalių grupės:

| Grupė | Detalės |
|---|---|
| Šaltiniai | Krepšys, Formos, Kalbos, Sąvokos (IE-CoR), Reikšmių tinklas (DatSemShift) |
| Matai | Garsinis atstumas (CLTS), Leksinis artumas, Genealoginis atstumas (Glottolog), Geografinis atstumas, Sutraukti pagal požymį (pvz. formų atstumai → kalbų), Atstumai ↔ panašumai |
| Grafai | Gauso branduolys (savaime derinamas), Svoris exp(−atstumas / τ), Panašumai → grafas |
| Sietai | Vienetų sietas (pagal požymį ar grupę), Apriboti pagal kitą, Didžiausia susieta grafo dalis, Stipriausi ryšiai |
| Spektrinė analizė | Laplaso spektras, Spektrinės grupės, Spektrinis išdėstymas, MDS, Medis (UPGMA), Glottolog šakos, Skaidinys pagal požymį |
| Rodikliai | Siluetas, Atitikimas medžiui (γ), Formos pastovumas, Reikšmės pastovumas, Sujungti rodiklius, Procentiliai |
| Vaisiai | Žemėlapis (ir „Atverti sode“), Savosios reikšmės, Kiek grupių?, Matrica, Dendrograma, Vienetų lentelė, Kryžminė lentelė, Grupių kortelės, Dviejų matų palyginimas (Mantel), Netikėtos poros, Atitikimas medžio lygiams, Rodiklių koreliacijos, Grupių permutacijų testas, Dviejų rodiklių sklaida, Užrašas |

Tarpiniai rezultatai 30 min. laikomi serverio atmintyje: pakeitus vieną parametrą, perskaičiuojamos tik nuo jo priklausančios detalės.

**Nauja detalė** – viena funkcija bet kuriame `kalba_sodas/vaiva/dirbtuves/` modulyje:

```python
@part("mano_sietas", "Sietai", title="Mano sietas", summary="Ką daro (rodoma sąraše).",
      inputs=[Port("ka", (ANY,), label="Ką sijoti")], outputs=[Port("ka", (SAME + "ka",), label="Kas lieka")],
      params=[Param("riba", "Riba", default=3, min=1, max=100, help="Ką reiškia.")])
def mano_sietas(ctx, inputs, params):
    obj = inputs["ka"]
    keep = [i for i, r in enumerate(obj.items.rows) if ...]   # ctx.drop(r, "priežastis") – kas neįtraukta
    return {"ka": obj.take(keep)}
```

Ji iškart atsiranda sąraše, tikrinama jungiant ir vykdoma. Vaisiaus detalė (`view=True`, be išėjimų) grąžina `{"kind": …, "data": …, "tiles": […], "notes": […]}`; naujai `kind` reikšmei naršyklėje reikia piešimo funkcijos `VIEWS.<kind>` (`static/dirbtuves.js`) – testas `test_every_fruit_kind_has_a_view_on_the_page` tai patikrina.

### LKEŽDB (Žemė → LKEŽDB)

Lietuvių kalbos etimologinio žodyno duomenų bazės (LKEŽDB) žodžiai aiškinami kalbos modeliu ir įtraukiami į tą pačią Neo4j bazę (paketas `kalba_lkezdb`). Duomenų talpykla – `duomenynai/lkezdb/puslapiai.db` (nuskaityti žodžiai, straipsniai, šaltinių sąrašas, aiškinimai, darbų eilė, variklio nustatymai). **Ji su programa nepateikiama**: be jos skirtukas LKEŽDB rodo, kad duomenų nėra, o visa kita veikia. Žemės skirtukas „LKEŽDB“ (`/zeme?skiltis=lkezdb&zodis=esmi` atveria žodį):

- **Žodžiai** – paieška, straipsniai (tekstas perskaitomas iš išsaugoto HTML: su tarpais, kursyvu rašytos kalbos formos pažymimos `⟨…⟩`), „Užklausa“ (ką gaus modelis), „Išaiškinti“ (į eilę; kartu ir įtraukti), „Įtraukti / Atnaujinti Neo4j“, „Perdaryti planą“ (be modelio), „Pašalinti iš Neo4j“; rodomos patikros pastabos, paaiškinimai, grafo planas ir visas JSON, pagal kurį sudarytas grafas.
- **Eilė** – fone vykdomi aiškinimai (lieka po serverio perkrovimo).
- **Variklis ir užklausa** – OpenAI suderinamas API (ChatGPT, LM Studio, kitas), modelis, raktas (byloje `.raktas`; kaip jį pakeisti – [OpenAI_raktas.md](OpenAI_raktas.md)), griežta JSON schema; užklausos (tinka tik su žyme `<!-- kalba-lkezdb-schema: 1 -->`).
- **Neo4j** – kiek LKEŽDB duomenų yra ir „Ištrinti visus LKEŽDB duomenis“: trinami tik mazgai su `dataset = "lkezdb"` ir jų ryšiai; kiti duomenynai, apribojimai ir indeksai lieka.

Grafo modelis (sutartis `kalba-neo4j/1.1`): `Entry -HAS_ARTICLE→ Article -HAS_CLAIM→ Claim -ABOUT→` objektai; `Lexeme -HAS_FORM→ Form`, `-USED_IN→ Languoid` (LKEŽDB kalba, vadinama kaip kituose duomenynuose – angliškai, pvz. „Lithuanian“, lietuviškas vardas `name_lt`; `CORRESPONDS_TO` Glottolog ir koordinatės iš jo, jei kodas žinomas – žodynas `LANGUAGES` byloje `kalba_lkezdb/plan.py`), `-HAS_SENSE→ Sense -DENOTES→` Concepticon sąvoka, `-HAS_FEATURE_VALUE→ FeatureValue -VALUE_OF→ Feature` (bendri visiems straipsniams), etimologiniai ryšiai (`DESCENDS_FROM`, `DERIVED_FROM`, `BORROWED_FROM`, `COGNATE_WITH`, `COMPARED_WITH`, `SOUND_CHANGE`, `REPLACES`, `VARIANT_OF`, `INFLUENCED_BY`), `Claim -SUPPORTED_BY→ Citation -CITES→ Source`, `Article -HAS_SOURCE→ Source`. Straipsnis su objektais tiesiogiai (`MENTIONS`) jungiamas tik tada, kai jų nepasiekia joks teiginys.

Komandinė eilutė: `python -m kalba_lkezdb explain esmi` (ir įtraukia; `--no-include`), `include`, `remove`, `replan`, `queue`, `counts`, `delete-all`, `raktas [--tikrinti]`.

### Duomenynai (Žemė → Duomenynai)

Sąsajoje galima:

- pažymėti, kuriuos duomenynus importuoti (importuojama numatyta eile);
- prieš importą pamatyti imtį grafu: kokie mazgai ir ryšiai būtų sukurti, su tikrais `display_name` (filtras, pvz. `Lithuanian`; nuoroda `http://127.0.0.1:8765/#iecor/Lithuanian`);
- skirtuke „Priklausomybės“ matyti, kokie mazgai tik nurodo išorinį raktą (◆ `ExternalIdentifier`) ir kuriame duomenyne (Glottolog, Concepticon) yra papildomi jų duomenys; jei jo nėra nei Neo4j, nei pažymėto – rodomas įspėjimas ir mygtukas jį pažymėti;
- skirtuke „Kokybė“ matyti mazgus, kurių pavadinimas atrodo kaip techninis ID;
- paleisti „Susieti su autoritetais“ (`resolve`);
- „Ištrinti visus Neo4j duomenis“ – mazgus, ryšius, apribojimus ir indeksus (reikia įvesti `IŠTRINTI`).

Jau įkelti rinkiniai praleidžiami: jei Neo4j yra baigtas (`completed`) to paties profilio importas, o katalogo failų dydžiai ir datos nepasikeitė, rinkinys neimportuojamas antrą kartą. Priverstinai importuoti iš naujo: UI varnelė arba `--force`.

Tas pats iš komandinės eilutės: `kalba-import import-all --config datasets.yaml --only glottolog,concepticon,iecor` ir `kalba-import resolve`.

## Visi 14 rinkinių į vieną Neo4j bazę

Rekomenduojama viską leisti iš virtualios aplinkos:

```bash
cd sodas
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -e '.[neo4j]'
```

Jei `.venv` jau sukurta ir paketas įdiegtas, užtenka:

```bash
cd sodas
source .venv/bin/activate
```

`import-all` skaito katalogų kelius iš vieno YAML failo. Pavyzdinis `datasets.yaml`:

```yaml
datasets:
  glottolog: duomenynai/glottolog
  concepticon: duomenynai/concepticon-data
  clts: duomenynai/clts
  iecor: duomenynai/iecor
  wold: duomenynai/wold
  lexibank_analysed: duomenynai/lexibank-analysed
  clics4: duomenynai/clics4
  norare: duomenynai/norare-data
  phoible: duomenynai/phoible
  wals: duomenynai/wals
  grambank: duomenynai/grambank
  dplace: duomenynai/dplace-cldf
  asjp: duomenynai/asjp
  datsemshift: duomenynai/datsemshift
```

Santykiniai keliai skaičiuojami nuo paties `datasets.yaml` katalogo.

Neo4j prisijungimo duomenis galima laikyti vietiniame `neo4j.yaml` faile. Jis įtrauktas į `.gitignore`, kad slaptažodis netyčia nepatektų į git. Pavyzdys:

```yaml
neo4j:
  uri: bolt://localhost:7687
  user: neo4j
  password: '<slaptažodis>'
  database: neo4j
```

Komandos `apply`, `resolve` ir `import-all` šį failą skaito automatiškai. Jei norisi naudoti kitą failą:

```bash
kalba-import resolve --neo4j-config neo4j.yaml
```

Dar galima naudoti aplinkos kintamuosius; jie perrašo `neo4j.yaml` reikšmes:

```bash
export KALBA_NEO4J_URI='bolt://localhost:7687'
export KALBA_NEO4J_USER='neo4j'
export KALBA_NEO4J_PASSWORD='<slaptažodis>'
export KALBA_NEO4J_DATABASE='neo4j'
```

Numatytoji importo eilė: `glottolog`, `concepticon`, `clts`, `iecor`, `wold`, `lexibank_analysed`, `clics4`, `norare`, `phoible`, `wals`, `grambank`, `dplace`, `asjp`.

Tik patikra be rašymo:

```bash
kalba-import import-all --config datasets.yaml --work-dir build/import-all --dry-run
```

Įprastas importas:

```bash
kalba-import import-all --config datasets.yaml --work-dir build/import-all --batch-size 1000
```

Importo metu būsena rašoma į terminalą per stderr: matysis `preflight`, kiekvieno rinkinio `planning`, `emitting`, `applying`, `verifying` ir `completed`. Dideliems rinkiniams galima didinti arba mažinti `--batch-size`; saugi pradžia yra `1000`, greitesniam serveriui dažnai tinka `5000` ar `10000`.

Dabartinis `plan` visą vieno rinkinio grafą laiko atmintyje. Vien CLICS4 turi daugiau kaip 8,7 mln. šaltinio eilučių, todėl viso jo planavimui reikės labai daug RAM; `--batch-size` keičia tik išvesties paketus ir šio atminties poreikio nemažina. `--dry-run` tikrina failus, metaduomenis ir ryšį, tačiau pilno plano arba Neo4j įrašymo neatlieka. Glottolog medžio `md.ini` failai įtraukiami kaip šaltinio įrašai su `Languoid` ir `PARENT_OF` ryšiais. CLICS4 abiejų CLDF modulių bendri fiziniai CSV importuojami vieną kartą.

Tęsimas po nutrūkimo:

```bash
kalba-import import-all --config datasets.yaml --work-dir build/import-all --resume
```

Žurnalas rašomas į `build/import-all/import-all-log.json`. Jame saugomi kiekvieno rinkinio `status`, `release_key`, profilio ir taisyklių SHA, pradžios/pabaigos laikai, eilučių, teiginių, neišspręstų nuorodų ir klaidų skaičiai. Slaptažodis į žurnalą nerašomas. Komanda niekada netrina esamų duomenų ir nenaudoja `DETACH DELETE`, reset ar Neo4j `import` katalogo.
