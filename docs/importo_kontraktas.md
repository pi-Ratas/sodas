# „Kalba“ Neo4j importo kontraktas v1.0

**Paskirtis.** Šis dokumentas yra specifikacija Python programai, kuri vienu paleidimu priima vieną pasirinktą duomenyno leidimą, iš jo sugeneruoja parametrizuotus Cypher importo paketus ir įkelia arba leidžia įkelti juos į Neo4j Community Edition. Jis apima bendrą branduolį, CLDF adapterį ir atskirus duomenynų profilius. Šiame etape programa **nekuriama**.

**Taikymo ribos.** Naudotojas turi katalogus `cldf-clts-clts-1c0b886`, `cldf-datasets-phoible-350563f`, `cldf-datasets-wals-0f5cd82`, `clics-clics3-97832b5`, `concepticon-data-3.4.0`, `concepticon-norare-data-17cbb42`, `dplace-cldf`, `glottolog`, `grambank-grambank-7ae000c`, `lexibank-analysed-2.2`, `lexibank-iecor-efd7442`, `lexibank-wold-1df62b9`. Katalogų failai šiame pokalbyje nepridėti; konkrečios lentelės, stulpeliai, leidimo SHA ir CLDF moduliai yra **tikrintini iš vietinių metaduomenų**, ne spėjami iš katalogo pavadinimo. Concepticon, Glottolog ir NoRaRe atveju būtini ir vietinių ne CLDF failų adapteriai. Visiems failams galioja jų licencijos ir citavimo reikalavimai.

**Norminių žodžių prasmė.** PRIVALO = importuotojas atmeta pažeidimą; TURĖTŲ = numatytoji taisyklė, nukrypimas įrašomas į profilį; GALI = pasirenkama galimybė. „Teiginys“ šiame dokumente yra atsekamas konkretaus leidimo faktas, o ne besąlygiška tiesa apie kalbą.

## 1. Pagrindinės garantijos

1. Kiekviena importuota eilutė, net jei jos semantika nežinoma, turi kelią `SourceRecord → SourceTable → DatasetRelease → Dataset`, o visi su ja sukurti faktai turi kelią iki tos eilutės. Bibliografinis `Source` yra **kitas** mazgas nei `SourceRecord`.
2. Bendri objektai jungiami tik pagal deklaruotą tapatybės taisyklę. Eilutės ID yra lokalus *konkrečiam duomenynui*, paprastai ir leidimui; vienodas rašymas, kalbos pavadinimas arba IPA simbolis savaime nereiškia tapatybės.
3. Duomenynų profiliai negali apeiti vardų sričių, kilmės kelių, idempotentiškumo ir nepatvirtintų sąsajų taisyklių. Naujas profilis gali pridėti savų tipų, savybių ir atvaizdavimo taisyklių.
4. Joks profilis neištrina kito šaltinio fakto. Keičiant leidimą ankstesnio leidimo įrašai ir jo teiginiai lieka; aktyvaus leidimo parinkimas yra užklausos arba atskiro administracinio rodinio taisyklė.
5. `provenance` savybė nededama **nei ant mazgų, nei ant ryšių**. Kilmė atsekama ryšiais per `Assertion`, `SourceRecord`, `DatasetRelease`, `ImportRun` ir, kur pateikta, `Source`.
6. Nežinomas, prieštaraujantis, tuščias ir neigiamas duomuo yra keturios skirtingos būsenos. Tuščia reikšmė nesukuria neigiamo teiginio.
7. „Be palaidų duomenų“ reiškia, kad nėra importuotų mazgų be kelio į leidimą, nėra semantinių teiginių be įrašo ir nėra neišspręstų nuorodų, tyliai pakeistų spėjamais patvirtintais ryšiais. Sąmoningai neprijungtas `SourceRecord` prie kanoninio `Lexeme` nėra klaida, jei eilutė išsaugota ir diagnostika aiški.

## 2. Trys sluoksniai ir tapatybė

| Sluoksnis | Mazgai | Tapatybės sritis | Paskirtis |
|---|---|---|---|
| Registras | `Dataset`, `DatasetRelease`, `ImportRun`, `SourceTable` | pastovus projekto ID; leidimo turinio SHA-256; paleidimo UUID | leidimai, pakartojimai ir lentelių schema |
| Eilučių apskaita | `SourceRecord`, `RawReference`, `Source`, `Citation` | leidimas + lentelė + PK / eilutės koordinatė; bibliografinis raktas leidime | nuostolių prevencija, FK, bibliografija |
| Semantika | `Languoid`, `Society`, `Lexeme`, `Form`, `Sense`, `Concept`, `CognateSet`, `ProtoForm`, `Sound`, `Feature`, `FeatureValue`, `Attestation`, `Text`, `TimeSpan`, `Assertion` ir profilio tipai | toliau pateiktos taisyklės | tyrimo grafas |

**Pastovus leidimo raktas:** `release_key = dataset_id + '@' + sha256(canonical_manifest)`. `canonical_manifest` yra surikiuotas visų šiam importui naudojamų įvesties failų santykinių kelių ir kiekvieno failo SHA-256 sąrašas, įskaitant CLDF metaduomenis, BibTeX, papildomus TSV ir profilio deklaruotas priklausomybes. Žmogiška versija, DOI ir git commit yra atskiros savybės. Identiskas katalogo turinys tuo pačiu `dataset_id` duoda tą patį `release_key`; pakitus vienam failui – naują. `profile_version`, `contract_version`, programos versija ir konfigūracijos SHA įrašomi į `ImportRun`; kitokia transformacija tame pačiame leidime kuria naują paleidimą, tačiau neturi tyliai perrašyti senųjų teiginių: semantinio teiginio rakte naudojamas taisyklių rinkinio SHA.

**Įrašo raktas:** `record_key = release_key + '/' + table_role_or_url + '/' + escaped_primary_key`. Naudojamas tik metaduomenyse deklaruotas PK (įskaitant sudėtinį); kai PK nėra, `relative_file_path + '#' + physical_row_number` ir eilutės kontrolinė suma, su pažyma `unstable_key=true`. Tokios eilutės tarp skirtingų leidimų automatiškai nesutapatinamos. Skirtingų katalogų kopijos to paties turinio neturi sukurti antro leidimo.

**Išoriniai identifikatoriai:** `ExternalIdentifier {scheme, value, key=scheme+'|'+value}`; `(:Entity)-[:IDENTIFIED_BY {validity,...}]->(:ExternalIdentifier)`. Leidžiamų schemų registras: `glottolog:glottocode`, `concepticon:conceptset`, `clts:bipa`, `phoible:inventory`, šaltinio lokalios schemos. Lokali schema privalo turėti `dataset_id` ir, jei kodai netvarūs, `release_key`. Unikalus identifikatorius negali būti priskirtas dviem nesutaikytoms to paties tipo esybėms; konfliktas stabdo susiejimą. Glottocode priskiriamas `Languoid`, ne automatiškai dialektui, kuriam duomenynas nurodė tik kalbą.

**Semantinės tapatybės lygiai:**

| Lygis | Kriterijus | Veiksmas |
|---|---|---|
| A | tas pats patikimas, tipo atžvilgiu unikalus išorinis ID ir patikrinta schema | `MERGE` bendrą objektą |
| B | tos pačios kilmės stabilus ID arba įregistruotas kuratoriaus patvirtintas atitikmuo | `MERGE` savo vardų srityje arba pagal patvirtintą atitikmenį |
| C | stipri profilyje apibrėžta sudėtinė tapatybė, be prieštaravimų; leksiką vertinti pagal §4 | kurti patvirtintą atitikmenį, užrašyti taisyklės versiją ir įrodymus |
| D | panašumas be pakankamo įrodymo | **ne** `MERGE`; sukurti `IdentityCandidate` ir `POSSIBLE_IDENTITY` su abiejų įrašų nuorodomis |
| E | neatitikimas arba homonimija | atskiri objektai, pasirinktinai `DISTINCT_FROM` su įrodymais |

`POSSIBLE_IDENTITY` leidžiamas tik tarp to paties semantinio tipo objektų; pats ryšys netampa įrodymu. Kandidatai deduplikuojami pagal surikiuotus du objektų raktus ir taisyklės versiją. Kandidato `reason`, `score` (jei algoritmas apskaičiavo), `status`, `rule_id` ir bent vienas susietas `Evidence` yra privalomi. Jis neturi pakeisti šaltinio vidaus FK. Pradinis konservatyvus slenkstis: jokių automatinių C lygio jungimų tarp skirtingų leksinių duomenynų, kol konkreti kalbų pora / įrašų pora nėra patvirtinta profilyje ar atitikmenų registre; tikslas – kandidatų reta, naudinga aibė, o ne visų panašių žodžių poros.

## 3. Branduolio duomenų žodynas

Visi mazgai turi `key` (unikalų savo etiketėje); vardas yra rodymo atributas, ne raktas. Nežinomos laiko ribos nėra `0`, o atviri intervalai turi `start` arba `end` be kitos ribos. Ryšiams, kurių nereikia pernaudoti kaip savarankiško identifikuojamo fakto, kilmę suteikia atskiras `Assertion`.

| Mazgas | Minimalios savybės | Reikšmė ir ribos |
|---|---|---|
| `Dataset` | `key`, `title` | registruotas šaltinis, pvz., `lexibank_analysed`; atskiras nuo jo poaibių |
| `DatasetRelease` | `key`, `version_label`, `manifest_sha256` | tikslus įvesties snapshot; DOI neprivalomas |
| `ImportRun` | `key`, `started_at`, `status`, `profile_version`, `config_sha256` | vykdymo ir diagnostikos vienetas |
| `SourceTable` | `key`, `url`, `role`, `schema_json` | CLDF/CSVW lentelė; saugo ir nežinomų stulpelių schemą |
| `SourceRecord` | `key`, `local_id`, `row_sha256`, `raw_json`, `row_number` | visos originalios reikšmės, įskaitant tuštumos ženklus; `raw_json` – JSON eilutė, ne Neo4j map savybė |
| `RawReference` | `key`, `column`, `target_raw`, `resolution_status` | FK, kurio importo momentu negalima išspręsti; tikras tikslas vėliau siejamas `RESOLVED_TO` |
| `Source` | `key`, `citation_key`, `bibtex_raw` | vienas bibliografinis objektas leidimo vardų srityje; DOI sujungia tik pagal patikrintą DOI |
| `Citation` | `key`, `locator`, `raw_ref` | konkreti nuoroda į šaltinį, pvz., puslapiai; gali būti keli vienam teiginiui |
| `Languoid` | `key`, `name`, `level` | kalba, dialektas ar šeima; Glottolog tapatybė pagal Glottocode |
| `Society` | `key`, `name` | D-PLACE visuomenė / populiacija, nelygi `Languoid` |
| `Lexeme` | `key`, `lemma_display`, `homonym_no` | leksinis vienetas; gali priklausyti kelioms kalbos atmainoms |
| `Form` | `key`, `written`, `phonetic` | konkretaus įrašo paliudyta forma; nereikia sujungti vien pagal rašybą |
| `Sense` | `key`, `gloss` | leksemos reikšmė duomenyno kontekste; kelios vienai `Lexeme` |
| `Concept` | `key`, `label` | Concepticon sąvoka arba lokali, aiškiai nurodyta sąvoka |
| `CognateSet` | `key`, `label` | šaltinio kognatų grupė; tarp šaltinių neidentifikuoti pagal panašų pavadinimą |
| `ProtoForm` | `key`, `reconstruction`, `notation` | šaltinio rekonstruota forma, su rekonstrukcijos statusu |
| `Sound` | `key`, `symbol`, `system` | CLTS garsas arba šaltinio fonetinis vienetas, nelygus fonemai |
| `Phoneme` | `key`, `symbol` | fonologinis vienetas konkrečiame inventoriuje |
| `Feature` / `FeatureValue` | `key`, `label`, `domain` / `key`, `raw_value` | WALS, Grambank, D-PLACE ar PHOIBLE požymis ir jo kodo vertė savo vardų srityje |
| `Text`, `Attestation`, `TimeSpan` | `key`, `title` / `key`, `quote` / `key`, `start`, `end`, `precision` | istoriniai liudijimai; naujo teksto adapterio vieta, ne teiginys, kad esami duomenynai turi tekstus |
| `Assertion` | `key`, `predicate`, `status`, `rule_id`, `rule_sha256`, `confidence` | konkretaus įrašo patvirtintas, atmestas arba ginčijamas faktas; kvalifikatoriai JSON arba susietais mazgais |
| `IdentityCandidate` | `key`, `reason`, `status`, `rule_id` | žmogaus sprendimo laukiantis sugretinimas |

**Privalomi struktūriniai ryšiai:** `DatasetRelease-[:RELEASE_OF]->Dataset`, `ImportRun-[:IMPORTS]->DatasetRelease`, `SourceTable-[:IN_RELEASE]->DatasetRelease`, `SourceRecord-[:IN_TABLE]->SourceTable`, `Assertion-[:DERIVED_FROM]->SourceRecord`, `Assertion-[:SUBJECT]->Entity`, `Assertion-[:OBJECT]->Entity` (arba `literal_json`), `Assertion-[:CITES]->Citation-[:REFERS_TO]->Source` (tik kai eilutė iš tiesų cituoja šaltinį). `ImportRun-[:PROCESSED_ASSERTION]->Assertion` saugo, kuris paleidimas sukūrė arba pakartotinai patikrino interpretaciją. `SourceRecord-[:REFERS_TO_RECORD]->SourceRecord` atspindi išspręstą FK; `RawReference` saugo neišspręstą. Vienas įrašas gali kurti kelis teiginius, vienas teiginys gali turėti kelis bibliografinius šaltinius. `Evidence` yra papildomas mazgas neeiliniam pagrindimui (taisyklių išvestys, lokatoriai, kuratoriaus sprendimai), privalomas tapatybės kandidatui; `SourceRecord` jo nepakeičia. Kiekvienas semantinis mazgas turi būti bent vieno `Assertion` subjektas ar objektas arba turėti aiškų `IDENTIFIED_BY` iš autoriteto; taip jis pasiekiamas iš įrašo arba iš registruoto identifikatoriaus.

**Patogūs semantiniai ryšiai:** `Lexeme-[:USED_IN]->Languoid`, `Lexeme-[:HAS_FORM]->Form`, `Lexeme-[:HAS_SENSE]->Sense`, `Sense-[:DENOTES]->Concept`, `Form-[:COGNATE_IN]->CognateSet`, `ProtoForm-[:RECONSTRUCTED_FOR]->CognateSet`, `Phoneme-[:IN_INVENTORY]->Inventory`, `Phoneme-[:REALIZED_AS]->Sound`, `Society-[:ASSOCIATED_WITH]->Languoid`, `Attestation-[:IN_TEXT]->Text`. Jie kuriami tik iš atitinkamų `Assertion`; vienodo tipo galinių mazgų pora gali turėti kelis šaltinius ir prieštaraujančius teiginius. Patogus ryšys yra **materializuotas rodinys**, perstatomas iš `Assertion`, turi deterministinį `assertion_key` arba `support_keys` sąrašą ir pats nėra vienintelis kilmės įrodymas. Pradinis įgyvendinimas gali apskritai negeneruoti šių tiesioginių ryšių, o naudoti užklausas per `Assertion`.

**Teiginio raktas:** `sha256(release_key | record_key | rule_sha256 | predicate | subject_key | object_key_or_literal | qualifier_canonical_json | occurrence_index)`. Jei keli šaltinio duomenys toje pačioje eilutėje įrodo tą patį faktą, `occurrence_index` atskiria tik tikrai skirtingus teiginius. Kelių šaltinių sutampantys faktai yra atskiri `Assertion`, bendri galiniai objektai; ginčo atveju jie neperrašomi.

## 4. Leksemos ir semantinių ribų sutartis

- `Lexeme` priklausymas atmainoms yra **daug su daug** ir pagrindžiamas kiekvienam `USED_IN` teiginiui; „vienas glottocode vienai leksemai“ netinka. Diachroniškai ar dialektiškai skirtingi vartojimai gali dalytis leksema tik su aiškiu pagrindu.
- Homonimai visada turi atskirus `Lexeme`. Ekvivalentinė rašyba, garsinė forma ir kalba nėra pakankamas `MERGE` raktas. Homonimo numeris, kai pateiktas, yra pagalbinis lokalus požymis, ne visuotinis ID.
- Poliseminė leksema turi vieną `Lexeme` ir keletą `Sense`. CLDF žodyno `Entry` gali suteikti leksemos lygmens šaltinio ID; Wordlist `Form` dažnai žymi reikšmei priskirtą formą, todėl iš jo **negalima automatiškai nuspręsti**, kad keli formos įrašai su ta pačia rašyba yra viena poliseminė leksema.
- Tame pačiame duomenyne identiška stabili `Entry` nuoroda leidžia B lygio sujungimą. Atskirų Wordlist formų sujungimas į vieną `Lexeme` leidžiamas tik jei šaltinis turi aiškią lexeme/entry nuorodą, arba kuratoriaus atitikmenį. Kitu atveju kuriamos atskiros **lokalios leksemos**, kurių `key` grįstas leidimo įrašo raktu; semantinis panašumas gali tapti kandidatu po filtravimo.
- Skirtingų duomenynų automatinis sujungimas leidžiamas tik su bendru, aiškiai leksemai skirtu patikimu ID arba kuratoriaus patvirtintu atitikmeniu. Glottocode ir Concepticon ID **neidentifikuoja leksemos**. Sąvokų sutapimas nėra reikšmių tapatumas: `Sense → Concept` reiškia šaltinio reikšmės sugretinimą su sąvoka, gali būti daug su daug, su neapibrėžtumu.
- `Form` saugo diplomatinę originalią rašybą ir atskirai normalizuotą paieškos formą / transkripciją. Diakritikų, kirčio, transliteracijos ar IPA normalizavimas skirtas kandidatų paieškai, niekada tapatybės įrodymui. `name` / `title` indeksai taip pat nėra tapatybės taisyklė.
- `CognateSet` grupės lokalios šaltiniui; kognatiškumas nėra `POSSIBLE_IDENTITY`. Skolinimasis nėra kognatiškumas; etimologiniai ir darybiniai ryšiai nėra leksemų tapatybė.

## 5. CLDF skaitymo ir neprarandamų duomenų taisyklės

1. Profilis deklaruoja metaduomenų JSON kelią arba aptikimo taisyklę. `pycldf` + CSVW metaduomenys interpretuoja modulį, `dc:conformsTo`, stulpelių `propertyUrl`, `foreignKeys`, `separator`, `null`, `datatype`, dialektą ir `dc:source`. Lentelės vaidmuo nustatomas pagal URI, ne failo pavadinimą; failo pavadinimas yra atsarginė tik profilyje patvirtinta taisyklė. CLDF `Generic` ir savitos lentelės įtraukiamos į eilučių sluoksnį.
2. Tikrinti metaduomenų sintaksę, failus, PK, FK, kodo domenus ir `pycldf` validaciją. `--strict` atmeta netaisyklingą duomenyną prieš rašymą. `--lenient` leidžia nesemantinius trūkumus, bet visus juos registruoja; klaidingų FK nepaverčia patvirtintais ryšiais. Nesuderinamo schemos pokyčio atveju profilis atmeta leidimą su schema diff.
3. Kiekviena deklaruotos lentelės eilutė išsaugoma `raw_json` su originaliais stulpelių vardais ir pažymėtu fiziniu numeriu; reikšmių sąrašai išskaidomi pagal CSVW `separator`, tačiau originali tekstinė reikšmė lieka. Įrašas gali turėti kelis lokalizuotus vardus, išnašas, komentarus, žemėlapių koordinates, nežinomus išplėstinius laukus; niekas nepradingsta dėl semantinio profilio ribotumo.
4. BibTeX skaityti pagal metaduomenų `dc:source`; šaltinio ID galioja leidime. `source_ID[locator]` skaidyti neprarandant originalios išraiškos, nuorodas tikrinti. Jei cituojamo šaltinio nėra BibTeX, įrašyti `RawReference` su klaidos būsena, ne išgalvoti bibliografinį įrašą.
5. FK tikrinami pagal nurodytą tikslinį stulpelį, įskaitant sudėtinius raktus ir daugiareikšmes nuorodas. Neišspręstas FK registruojamas `RawReference`, nurodant eilutę, stulpelį ir reikšmę; semantinis ryšys neatliekamas. Nukreipimas į kitą leidimą gali vykti tik per deklaruotą išorinio identifikatoriaus schemą ar atitikmenų registrą.
6. Už CLDF ribų esantys, tačiau naudojami failai (Concepticon TSV, Glottolog katalogai, NoRaRe TSV, projekto papildomi metaduomenys) aprašomi `SourceTable` analogais ir importuojami tomis pačiomis eilutės, FK, teiginio ir diagnostikos taisyklėmis. Vien README ar programos kodas nėra automatiškai duomenų lentelė: profilis vardija reikšmingus failus; neapdorotų failų sąrašas pateikiamas ataskaitoje.
7. Nešvarūs duomenys (`null`, neteisingi kodai, dublikatinis PK, prieštaraujantis ID) niekada negali tyliai išnykti. `strict` blokavimas arba karantinas `lenient` režimu su tikslia priežastimi ir `record_key`.

## 6. Duomenynų profiliai

Kiekviena eilutė apibrėžia **profilio ketinimą**, o tikrieji atvaizdavimo stulpeliai įtvirtinami tik iš vietinės schemos. Ženklas „jei“ reiškia privalomą patikrą, o ne pažadą, kad failas tikrai turi tą lauką. `Dataset` ID čia yra siūlomi stabilūs vardai; kartą paskelbus jų pervadinimas yra migracija.

| `dataset_id` / vietinis katalogas | Šaltinio vaidmuo ir semantinis atvaizdavimas | Jungimas ir apsaugos |
|---|---|---|
| `glottolog` / `glottolog` | katalogo `Languoid`, genealoginiai `PARENT_OF` teiginiai, vardai, geografija, bibliografija; vietiniame medyje aptikti leidimą, kodus ir jų istoriją | Glottocode – A lygio `Languoid` ID; ne visos atmainos laikomos kalbomis; pasikeitus kodams tik oficialūs atitikmenys, ne spėjimai |
| `concepticon` / `concepticon-data-3.4.0` | `Concept`; konceptų sąrašų elementai ir jų susiejimo teiginiai; saugoti originalią gloss ir kalbą | Concepticon concept set ID – A lygis; sąrašo vietinis numeris nėra globalus; keli sugretinimai nepaverčiami lygybe |
| `clts` / `cldf-clts-clts-1c0b886` | `Sound`, sistemų simboliai, požymių vertės ir transkripcijos atitikmenys pagal faktiškai pateiktą metaduomenų modulį | CLTS sistemos + kodas; panašūs Unicode simboliai nesujungiami automatiškai; sistema ir interpretacija būtinos |
| `phoible` / `cldf-datasets-phoible-350563f` | `Inventory`, `Phoneme`, `Sound` atitikmenys jei nurodyti, fonemų požymiai, šaltiniai | inventoriaus vietinis ID išsaugomas; viena kalba gali turėti kelis inventorius; fonema nėra visuotinė CLTS garso tapatybė |
| `wals` / `cldf-datasets-wals-0f5cd82` | `Feature`, `FeatureValue`, kalbai priskirti `Assertion` iš `ValueTable`, `CodeTable` ir šaltinių | WALS parametrų/kodų raktai vardinėje srityje; nebandyti sutapatinti su Grambank požymiu pagal panašų vardą |
| `grambank` / `grambank-grambank-7ae000c` | analogiški tipologiniai teiginiai; tikrinti vietinį kodavimo ir negalimų / nežinomų reikšmių aprašą | Grambank savi parametrų ir kodų raktai; trūkstama vertė nėra nulis |
| `dplace` / `dplace-cldf` | `Society`, kultūros/aplinkos `Feature` ir jos reikšmės, geografiniai duomenys, ryšys su `Languoid` pagal pateiktą ID | visuomenės netapatinti su kalba; išsaugoti ryšio pagrindą, kelių kalbų galimybę, laiko ir šaltinio kontekstą |
| `lexibank_analysed` / `lexibank-analysed-2.2` | `Lexeme`, `Form`, `Sense`, `Concept`; jei lentelės pateikia kognatų sprendinius – `CognateSet`; tikrus proto įrašus atskirti nuo analizėje naudojamų protokalbės įrašų | duomenyno kilmės ID ir leidimo ID būtini, nes agregatas apima kitus rinkinius; `CogCore`, `ProtoCore` yra **kolekcijos narystės**, `CollectionMembership` teiginiai, ne atskiri `DatasetRelease` |
| `iecor` / `lexibank-iecor-efd7442` | CLDF formos, reikšmės, kognatų sprendiniai, chronologija ir skolinimosi duomenys **jei** atitinkamos lentelės / laukai pateikti | `iecor` ir agregato IE-CoR kopijų šaltinio įrašai lieka savi; patvirtinta kilmės ID kryžminė lentelė leidžia sujungti semantinius objektus, bet ne du teiginius į vieną |
| `wold` / `lexibank-wold-1df62b9` | recipientinė forma / įrašas, šaltinio nurodytas donoras, skolinimosi teiginys, etimologiniai komentarai | donoro kalbos pavadinimas nėra donoro `Lexeme` ID; `BORROWED_FROM` sukurti tik kai donoro leksinis įrašas vienareikšmiškai nurodytas; kitaip `BorrowingEvent` su donorinės kalbos / žaliu tekstu ir neapibrėžtumu |
| `clics3` / `clics-clics3-97832b5` | koleksifikacijos stebėjimai iš formų ir konceptų; atskirai išvestinis sąvokų tinklo ryšys su skaičiavimo taisykle | `COLEXIFIES` nėra `Concept` lygybė ar įrodytas semantinės kaitos kelias; kalbų ir sąvokų ID jungti tik pagal deklaruotus išorinius kodus |
| `norare` / `concepticon-norare-data-17cbb42` | normos, reitingai ir sąvokų santykiai su `Measure`, `Measurement`, vienetais, kalba ir tyrimo šaltiniu | tikrinamas tikras lokalus formatas; negalima visų skalių verčių suvesti į vieną `FeatureValue`; matavimo populiacija ir metodas paliekami |

**Svarbus apribojimas.** CLICS tinklo kraštines reikia skaičiuoti iš stebėjimų su leidimo ir filtro versija; jų negalima importuoti kaip vienintelio pirminio įrodymo, jei turimos pirminės formos. WOLD donorinė informacija gali būti dalinė. ProtoCore narystė nereiškia, kad kiekviena protokalbės forma turi nepriklausomą patikimą rekonstrukcijos įrodymą. D-PLACE, Grambank, WALS ir PHOIBLE išlaiko savus tipologinių / fonologinių požymių kodus net kai vertės panašios.

### 6.1 Profilio failo privaloma schema (pavyzdys, ne patvirtinta vietinių failų schema)

```yaml
contract: kalba-neo4j/1.0
dataset_id: iecor
profile_version: 1.0.0
input:
  kind: cldf
  metadata_glob: "cldf/*metadata.json"
  require_exactly_one_metadata: true
  extra_files: []
requires:
  authorities: [glottolog, concepticon]
  mode: resolve_or_defer
roles:
  form: "http://cldf.clld.org/v1.0/terms.rdf#FormTable"
  cognate: "http://cldf.clld.org/v1.0/terms.rdf#CognateTable"
bindings:
  language_id: {term: "http://cldf.clld.org/v1.0/terms.rdf#languageReference"}
  concept_id: {term: "http://cldf.clld.org/v1.0/terms.rdf#parameterReference"}
rules:
  - id: form-to-language-v1
    table_role: form
    when: "language_id_present"
    subject: "local_form(record_key)"
    predicate: "ATTESTED_IN_VARIETY"
    object: "resolve_language(language_id)"
    unresolved: defer
    evidence: ["record_key", "language_id"]
policies:
  lexical_identity: source_entry_only
  unknown_columns: retain_raw
  ambiguous_reference: defer
  external_identity: authoritative_ids_only
```

Programos profilių interpretavimo kalba PRIVALO būti saugi ir ribota: vardinės funkcijos / deklaratyvios išraiškos, be savavališko `eval` ar nepatikrintos Python išraiškos. Tikslūs `roles` ir `bindings` sulyginami su aptikta schema; lauko nebuvimas sukuria diagnostiką ir neturi sukurti tuščio tikslo. Profilio plėtiniai naudoja vardų sritį `extension:<owner>:<name>` ir deklaruoja migraciją, jei keičia galiojančią semantiką.

## 7. Užkrovimo programa ir Cypher sutartis

**Sąsaja:** `kalba-import inspect --dataset iecor --path /kelias/lexibank-iecor-efd7442 --profile profiles/iecor.yaml`; `plan` sukuria ataskaitą ir deterministinius paketų failus; `emit` sukuria parametrizuotų užklausų `.cypher` šablonus bei NDJSON parametrų partijas; `apply --database neo4j --batch-size N` naudoja oficialią Python Neo4j tvarkyklę ir transakcijas; `verify` tikrina pateiktą leidimą. `--strict` numatytasis; `--lenient` su karantinu. Nesieti importo su `LOAD CSV file:///`, taigi Linux Mint / Neo4j `import` katalogas nėra būtinas. Jei norima gryno `.cypher`, sugeneruoti saugiai ekranuotą, atkuriamą variantą tik mažoms partijoms; numatytasis išvesties formatas turi aiškų parametrų failą ir paleidimo instrukciją, nes viena Cypher eilutė masyviam duomenynui nepraktiška.

**Eiga:** (1) `inspect`: manifestas, metaduomenų vaidmenys, FK, šaltiniai, kodų domenai, schema diff; (2) `plan`: validacija, tapatybių sprendimas / atidėjimas, paketo planas ir numatomų mazgų, teiginių, kandidatų skaičiai; (3) registras ir schemos apribojimai; (4) `SourceTable`, `SourceRecord`, bibliografija, vidiniai FK; (5) identifikatorių autoritetai ir semantiniai mazgai; (6) `Assertion` ir jo galai / citatos; (7) nebūtini materializuoti ryšiai; (8) patikra ir užbaigtas `ImportRun`.

**Priklausomybių logika:** galima importuoti bet kurį duomenyną atskirai. Jei Glottolog / Concepticon / CLTS dar nėra įkelti, įrašomas lokalus objektas ir `RawReference` su `pending` arba patikimo išorinio ID „stub“ `ExternalIdentifier`, tačiau **ne** melagingas užpildytas autoriteto `Languoid` / `Concept` / `Sound`. Kai autoritetas atkeliauja, `resolve` komanda atnaujina nuorodas / patvirtina tapatybę ir sukuria naujus atsekamus atitikmenų teiginius, išsaugodama pirminius įrašus. `resolve` privalo būti idempotentiška.

**Cypher šablonų principas:** naudojami parametrų masyvai ir `UNWIND $rows AS row`, `MERGE` pagal vieną stabilų `key`; po `MERGE` atnaujinamos tik to paties objekto nekeičiančios savybės, konfliktą keliant į diagnostiką. Etiketės, ryšių tipai ir savybių pavadinimai gaunami tik iš programos leistinų vardų sąrašo, ne iš nepatikimo CSV; reikšmės visada parametrizuojamos. Pavyzdys:

```cypher
UNWIND $rows AS row
MERGE (r:SourceRecord {key: row.record_key})
ON CREATE SET r.local_id = row.local_id, r.raw_json = row.raw_json,
              r.row_sha256 = row.row_sha256, r.row_number = row.row_number
WITH r, row
MATCH (t:SourceTable {key: row.table_key})
MERGE (r)-[:IN_TABLE]->(t)
```

Jei to paties `record_key` jau esamo `row_sha256` skiriasi, prieš importą aptikti konfliktą ir sustoti; `MERGE` vienas pats to netikrina. Vienos `Assertion` sukūrimą, `DERIVED_FROM`, `SUBJECT`, `OBJECT` ir citatas daryti toje pačioje transakcijoje. Partijos po klaidos kartojamos be dubliavimo. Visos užklausos vienoje partijoje rūšiuojamos pagal raktą; partijos dydis konfigūruojamas. `ImportRun.status` = `planned/running/completed/failed`; dalinis `failed` atstatomas paleidus su tais pačiais raktais, o naujas interpretacijos taisyklių rinkinys kuria naujus teiginius.

**Indeksų / apribojimų minimumas** (Neo4j Community aplinkoje, suderinamumą su įdiegtos Neo4j versijos Cypher sintakse programa patikrina):

```cypher
CREATE CONSTRAINT dataset_key IF NOT EXISTS FOR (n:Dataset) REQUIRE n.key IS UNIQUE;
CREATE CONSTRAINT release_key IF NOT EXISTS FOR (n:DatasetRelease) REQUIRE n.key IS UNIQUE;
CREATE CONSTRAINT record_key IF NOT EXISTS FOR (n:SourceRecord) REQUIRE n.key IS UNIQUE;
CREATE CONSTRAINT table_key IF NOT EXISTS FOR (n:SourceTable) REQUIRE n.key IS UNIQUE;
CREATE CONSTRAINT assertion_key IF NOT EXISTS FOR (n:Assertion) REQUIRE n.key IS UNIQUE;
CREATE CONSTRAINT external_id_key IF NOT EXISTS FOR (n:ExternalIdentifier) REQUIRE n.key IS UNIQUE;
```

Analogiškas unikalaus `key` apribojimas PRIVALO būti sukurtas kiekvienai įjungto profilio semantinei etiketei, `ImportRun`, `RawReference`, `Source`, `Citation`, `IdentityCandidate`. Naudoti aiškias `MATCH` užklausas ir unikalius raktus, ne GDS ar Neo4j Enterprise funkcijas. Daugiareikšmes savybes laikyti Neo4j leistinais primityvų sąrašais arba `*_json` eilutėmis; nebandyti išsaugoti `map` kaip mazgo savybės.

## 8. Suderinamumo, atnaujinimo ir kokybės vartai

**Versijos.** Bendras kontraktas turi semantinę versiją. Pridėjus naują profilį ar laisvai pasirenkamą lauką – minor; pakeitus tapatybės taisyklę, ryšio prasmę, raktą arba `Assertion` struktūrą – major ir aiški migracija. Profilis deklaruoja suderinamą branduolio major ir palaikomus šaltinio schemos pirštų atspaudus. Naujasis duomenyno leidimas, jei turi naują struktūrą, reikalauja profilį peržiūrėti; turinio pasikeitimas be struktūros pasikeitimo vis tiek yra naujas `DatasetRelease`.

**Privalomi `inspect/plan` rezultatai:** failų manifestas; licencija ir citata (jei yra); kiekvienos lentelės vaidmuo ir eilučių skaičius; nežinomų lentelių / stulpelių sąrašas; PK ir FK problemos; neišspręstų išorinių kodų sąrašas; numatomi A/B/C/D tapatybės sprendimai su priežastimis; galimos dubliuotos agregato kopijos; autoritetų leidimai, su kuriais buvo lyginta; atmetimo ir karantino įrašai. Nepateikta licencija nežymima kaip laisva licencija.

**Privalomos patikros po `apply`:**

| Vartai | Priėmimo sąlyga |
|---|---|
| Eilučių išsaugojimas | kiekvienai lentelės eilei tiksliai vienas `SourceRecord`, išskyrus aiškiai karantinuotas, kurios taip pat turi įrašą ir diagnozę |
| Kilmės kelias | kiekvienas teiginys turi tiksliai vieną `DERIVED_FROM` įrašą; įrašas pasiekia leidimą ir duomenyną |
| Ryšių galai | nė vienas patvirtintas `Assertion` neturi trūkstamo `SUBJECT` ar numatyto `OBJECT` |
| Nuorodos | visi vidiniai FK išspręsti arba kiekvienas turi `RawReference` ir aiškią būseną; 0 tyliai ignoruotų |
| Tapatybė | 0 prieštaraujančių unikalių išorinių ID; 0 susiliejimų vien pagal gloss, rašybą ar kalbos vardą |
| Pakartotinis importas | tą patį `release_key` ir `rule_sha256` paleidus dar kartą, eilučių, semantinių mazgų ir teiginių skaičiai nesikeičia |
| Skirtinga tvarka | importavus A→B ir B→A, galutinės patvirtintos tapatybės ir atidėtų nuorodų išsprendimas sutampa (po `resolve`) |
| Agregato sutapimas | IE-CoR/WOLD savarankiškų leidimų ir Lexibank agregato įrašų kilmė lieka atskira; patvirtinta pora dalijasi semantiniu objektu, faktai nesudvigubinami kaip nepriklausomi šaltiniai skaičiavime |

**Agregatų taisyklė:** kai agregatas kopijuoja pirminį rinkinį, žymėti `SourceRecord-[:DERIVED_FROM_RECORD]->SourceRecord`, jei tai pagrįsta stabiliais kilmės ID; kitu atveju saugoti `possible_derivative` kandidatą. Analitinė užklausa gali rinktis tik pirminius arba skaičiuoti išvestines kopijas vieną kartą; importuotojas nepanaikina nė vieno įrašo. Derivacijos faktas turi savo `Assertion` / pagrindą.

**Kontrolinis mažas pavyzdys.** IE-CoR eilutė `f1` su Glottocode `xxxx1234`, Concepticon `100`, forma `X`, priskirta kognatų grupei `c1`, sukuria `SourceRecord(f1)`, lokalų `Lexeme` ir `Form`, `Sense`, nuorodas į autoritetų `Languoid` ir `Concept` (jei ID egzistuoja), `CognateSet(iecor:c1)` ir atskirus `Assertion` kiekvienam semantiniam ryšiui. Jei tas pats `X` yra kito duomenyno eilutėje, jos `SourceRecord` ir `Assertion` yra atskiri; leksemos lieka atskiros, kol nustatomas A/B/C lygio įrodymas. Jei `xxxx1234` Glottolog nėra, eilutė išlieka, o kalbos nuoroda pažymima `pending` – neįkuriama tariama kalba.

## 9. Užduočių seka programos autoriui

1. Implementuoti `inspect` ir schemos inventorių visiems 12 nurodytų katalogų; surinkti realius metaduomenų failus, lentelių vaidmenis, licencijas, `dc:source`, papildomus TSV, PK/FK. Pateikti konkrečių schemų lentelę ir pakeisti šio dokumento profilinių laukų sąlygines vietas; nepagrįstos prielaidos turi likti pažymėtos.
2. Įgyvendinti bendrą registrą, manifestą, `SourceRecord`, `Source`, FK, klaidų ataskaitą, `plan/emit/apply/verify`; atlikti vieno mažo duomenyno pakartojimo testą.
3. Autoritetai eilės tvarka: Glottolog, Concepticon, CLTS. Tik tada profiliniai WALS, Grambank, D-PLACE, PHOIBLE ir leksiniai duomenynai. Programa turi veikti ir kitokia tvarka su `resolve_or_defer`.
4. Leksinių duomenų profiliai: IE-CoR, Lexibank analysed (su CogCore/ProtoCore naryste), WOLD, CLICS; parengti agregato ID kryžmines lenteles ir atlikti skirtingos eilės / dvigubo skaičiavimo testus. NoRaRe pritaikyti pagal tikrą TSV / CLDF struktūrą.
5. Tik po to įjungti automatinius C lygio leksemų atitikmenis atskiroje, peržiūrėtoje taisyklių versijoje. `POSSIBLE_IDENTITY` sudaryti tik tiksliniams retiems kandidatams; kuratoriaus sprendimus saugoti versijuotai.

**Pristatymo kriterijus programai:** galima pasirinkti vieną iš dvylikos rinkinių pagal `--dataset` ir `--path`, gauti `inspect` / `plan` / parametrizuotą Cypher, jį idempotentiškai pritaikyti be GDS ir be Neo4j `import` katalogo, išlaikyti visus įtrauktų lentelių įrašus bei jų kilmę, po skirtinga tvarka atlikto importo patikrinti tapatybių ir nuorodų teisingumą. Vien šio kontrakto nepakanka patvirtinti konkrečių vietinių failų struktūros: pirmoji programos funkcija būtent ją turi inventorizuoti.

## 10. Techninis pagrindas

- [CLDF specifikacija](https://github.com/cldf/cldf/blob/master/README.md): metaduomenų vaidmenys, CSVW, FK, `separator`, BibTeX ir moduliai.
- [CLDF svetainė](https://cldf.clld.org/): CLDF apimtis ir specifikacijos versija.
- [Lexibank analysed CLDF metaduomenys](https://github.com/lexibank/lexibank-analysed/blob/main/cldf/wordlist-metadata.json) ir [darbo eiga](https://github.com/lexibank/lexibank-analysed/blob/main/workflow.md): agregato ir kolekcijų struktūros tikrinimo vieta.
- [D-PLACE CLDF aprašas](https://github.com/D-PLACE/dplace-cldf/blob/master/cldf/README.md), [Grambank CLDF aprašas](https://github.com/grambank/grambank/blob/master/cldf/README.md), [NoRaRe projekto aprašas](https://github.com/concepticon/norare-data/blob/master/README.md): profilių tikrinimo pradžia.

Šios nuorodos yra specifikacijos / projektų orientyrai. Jos nepakeičia naudotojo turimų katalogų `inspect` rezultatų ir nėra teiginys, kad visų nurodytų versijų laukai yra vienodi.
