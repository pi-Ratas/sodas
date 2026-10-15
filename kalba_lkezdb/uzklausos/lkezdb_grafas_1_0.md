<!-- kalba-lkezdb-schema: 1 -->
# LKEŽDB straipsnių analizė Kalbų grafui (1.0)

## 1. Užduotis

Tau pateikiamas vienas Lietuvių kalbos etimologinio žodyno duomenų bazės
(LKEŽDB) žodis ir jo straipsniai. Išanalizuok kiekvieną straipsnį ir
grąžink struktūrizuotą jo turinį: kalbinius objektus, reikšmes,
lingvistines savybes, autoriaus teiginius, etimologinius ryšius ir
tekste cituojamus šaltinius.

Iš tavo atsakymo programa sukurs Neo4j grafą, kuriame jau yra Glottolog
kalbų medis, Concepticon sąvokos, IE-CoR kognatai, CLTS garsai ir kiti
duomenynai. Todėl svarbu:

- kiekvienas faktas JSON'e aprašomas **lygiai vienoje vietoje** (žr. 3 skyrių);
- kalbos ir reikšmės pateikiamos taip, kad programa galėtų jas susieti su
  Glottolog ir Concepticon;
- tai, ką sako straipsnis, griežtai atskirta nuo to, ką išvedi tu.

Nieko neišgalvok. Autoriaus teiginius imk tik iš pateikto teksto.
Grąžink vieną validų JSON objektą, be Markdown ir be teksto už jo ribų.
Negeneruok Cypher, UUID ar duomenų bazės identifikatorių – juos kuria
programa.

## 2. Įvestis

```json
{
  "zodis": {"GUID": "...", "zodis": "esmi"},
  "straipsniai": [
    {"GUID": "...", "antraste": "esmi", "reiksme": "to be",
     "tekstas": "...", "saltinis": "Robinson 1977", "metai": "1977", "vieta_saltinyje": "226"}
  ]
}
```

- `tekstas` – straipsnio tekstas. **Kursyvas pažymėtas `⟨…⟩`**: LKEŽDB
  kursyvu rašo cituojamas kalbos formas, todėl `⟨esmi⟩` yra kalbos
  forma, o ne aprašo žodis. Žvaigždutė prieš formą (`*⟨esmei⟩`) reiškia
  rekonstrukciją. Pačių `⟨ ⟩` į atsakymą nerašyk.
- `antraste` – žodis ar forma, apie kurią straipsnis (dažniausiai
  lietuvių). `reiksme` – LKEŽDB nurodyta jos reikšmė.
- `saltinis`, `metai`, `vieta_saltinyje` – paties straipsnio šaltinis.
  Programa jį susieja pati: **nekurk iš jo `citations`**.
- Kalbų santrumpos įprastos LKEŽDB: lie. – lietuvių, s. lie. – senoji
  lietuvių, la. – latvių, pr. – prūsų, s. i. – senoji indų (sanskritas,
  vedų), het. – hetitų, got. – gotų, lot. – lotynų, gr. – senovės
  graikų, s. sl. – senoji bažnytinė slavų, arm. – armėnų, ide. –
  indoeuropiečių prokalbė ir t. t.

## 3. Atsakymo struktūra ir „viena vieta kiekvienam faktui“

```json
{
  "articles": [
    {
      "GUID": "straipsnio GUID be jokių pakeitimų",
      "paaiskinimas": "...",
      "entities": [],
      "meanings": [],
      "meaning_groups": [],
      "features": [],
      "claims": [],
      "relations": [],
      "citations": [],
      "notes": []
    }
  ]
}
```

Grąžink po vieną objektą kiekvienam įvesties straipsniui; `GUID`
perrašyk pažodžiui. Lokalūs ID galioja vieno straipsnio ribose:
`e1…` objektams, `m1…` reikšmėms, `g1…` reikšmių grupėms, `f1…`
savybėms, `c1…` teiginiams, `s1…` citatoms, `n1…` pastaboms.
Visi schemos laukai privalomi: jei duomenų nėra – `null` arba `[]`.

Kiekvienas ryšys grafe atsiranda **tik iš vieno lauko**:

| Ryšys grafe | Iš kur | Kur jo NEKARTOTI |
|---|---|---|
| lema → forma | `entities[].lexeme_id` | ne `relations` |
| objektas → reikšmė | `meanings[].of` | ne `relations` |
| reikšmė → reikšmių grupė | `meaning_groups[].members` | ne `relations` |
| objektas → savybė | `features[].applies_to` | ne `relations` |
| teiginys → objektas | `claims[].about` | – |
| teiginys → teiginys | `claims[].supports`, `claims[].contradicts` | ne `relations` |
| teiginys → citata | `claims[].citations` | ne `citations[].claims` |
| etimologinis ryšys tarp objektų | `relations[]` | – |

Straipsnis grafe jungiamas su savo teiginiais, o teiginiai – su tuo,
apie ką jie kalba. Todėl `claims[].about` rašyk tik tuos objektus, apie
kuriuos teiginys kalba tiesiogiai; programa nejungs straipsnio su
kiekvienu objektu atskirai.

## 4. Kalbiniai objektai: `entities`

```json
{
  "id": "e1",
  "kind": "Form",
  "written": "esmi",
  "canonical": null,
  "language_text": "s. lie.",
  "language": "senoji lietuvių",
  "glottocode": "lith1251",
  "part_of_speech": "verb",
  "morphology": [{"category": "person", "value": "1"}, {"category": "number", "value": "singular"},
                 {"category": "tense", "value": "present"}],
  "lexeme_id": "e3",
  "homonym_no": null,
  "is_headword": true,
  "reconstruction": null,
  "provenance": "article",
  "confidence": null,
  "evidence": "senosios lietuvių kalbos esmi"
}
```

`kind`:

- **`Lexeme`** – žodyno žodis (lema) konkrečioje kalboje, užrašytas
  įprasta žodyno forma: lietuvių veiksmažodis – bendratimi (`būti`),
  daiktavardis – vardininko vienaskaita. Lema niekada nėra gramatinė
  klasė, paradigma ar apibendrinimas („atematinės veiksmažodžių formos“,
  „tematinės formos“, „i-kamieniai“ – tai `features`). Jei straipsnyje
  aptariama forma, o jos lema tekste neminima, bet tau patikimai žinoma
  (pvz. `esmi`, `esti` → `būti`), sukurk `Lexeme` su
  `provenance: "llm_inference"`, `confidence` ir `evidence: null`. Jei
  lema neaiški – jos nekurk.
- **`Form`** – konkreti paliudyta žodžio forma (asmenuota, linksniuota,
  dalyvis, tarminė, istorinė rašyba). Jos lemą nurodyk `lexeme_id`.
- **`ProtoForm`** – rekonstruota, nepaliudyta forma (su `*`). Lauke
  `reconstruction` nurodyk `{"proto_language": "indoeuropiečių", "level": "root"}`;
  `level`: `root`, `stem`, `affix`, `word`, `ending`.
- **`Attestation`** – konkretus užrašymas konkrečiame šaltinyje, kai
  straipsnis jį skiria nuo bendresnės formos (pvz. prūsų katekizmo
  rašyba). Jos formą ar lemą nurodyk `lexeme_id`.

Laukai:

- `written` – forma taip, kaip tekste: su diakritika, kirčiu, ilgumu,
  `*`, laringalais, skiemeniniais ženklais.
- `canonical` – tik jei aiški kita kanoninė forma (pvz. be kirčio
  ženklų nekeičiant garsų); kitaip `null`.
- `language_text` – kalbos santrumpa kaip tekste; `language` – pilnas
  lietuviškas pavadinimas; `glottocode` – Glottolog kodas tik tada, kai
  esi tikras (`lith1251` lietuvių, `latv1249` latvių, `prus1238` prūsų,
  `sans1269` sanskritas, `hitt1242` hetitų, `goth1244` gotų,
  `lati1261` lotynų, `anci1242` senovės graikų, `chur1257` senoji
  bažnytinė slavų, `clas1249` senoji armėnų); prokalbėms ir abejojant –
  `null`. Programa kodą patikrina.
- `morphology` – paprastos gramatinės kategorijos poromis. Kategorijos:
  `person`, `number`, `tense`, `mood`, `voice`, `case`, `gender`,
  `degree`, `aspect`, `nonfinite` (infinitive, participle, gerund…),
  `definiteness`. Reikšmės angliškai mažosiomis (`singular`, `present`,
  `nominative`…). Jas galima nustatyti ir iš bendrųjų žinių, jei forma
  vienareikšmė.
- `is_headword` – `true` tik objektui, kuris atitinka straipsnio
  `antraste` (paprastai vienas).
- `provenance`: `article` – tiesiogiai tekste; `article_inference` –
  aiškiai išplaukia iš kelių teksto duomenų; `llm_inference` – iš tavo
  bendrųjų žinių. `confidence` (`high`/`medium`/`low`) – tik išvedamiems,
  `article` atveju `null`.

Nesuliek skirtingų kalbų, homonimų ar rekonstrukcijos lygmenų. Nekurk
tarpinių formų, kurių tekste nėra.

## 5. Reikšmės: `meanings`

```json
{"id": "m1", "gloss": "būti", "language": "lietuvių", "of": ["e3"],
 "kind": "source_gloss", "concepticon_gloss": "BE", "evidence": "..."}
```

- Kiekvieną argumentui svarbią reikšmę – atskirai; artimų reikšmių
  nesuliek („tampu“, „esu buvęs“, „būsena“ – trys reikšmės).
- `of` – objektai, turintys šią reikšmę.
- `kind`: `source_gloss`, `contextual`, `reconstructed`, `semantic_component`, `other`.
- `concepticon_gloss` – Concepticon glosa didžiosiomis raidėmis (`BE`,
  `MOON`, `FIRE`), tik jei reikšmė aiškiai ta pati sąvoka; kitaip `null`.
  Programa patikrina, ar tokia sąvoka yra.

`meaning_groups` – tik kai kelios atskiros reikšmės aiškiai priklauso
bendrai semantinei sričiai: `{"id": "g1", "label": "būvis",
"description": "...", "members": ["m1", "m2"], "evidence": "..."}`.
Reikšmės lieka atskiros.

## 6. Lingvistinės savybės: `features`

Klasifikacijos, svarbios argumentui ir vėlesnėms užklausoms: fleksijos
tipas, kamieno klasė, abliauto laipsnis, daryba, reduplikacija ir pan.
Ta pati savybė visuose straipsniuose turi būti užrašyta vienodai, todėl
`feature` ir `value` rinkis iš šių sąrašų (anglų kalba, mažosios, su
pabraukimu):

| `feature` | tipinės `value` |
|---|---|
| `inflection_class` | `athematic`, `thematic`, `semithematic` |
| `stem_class` | `a_stem`, `o_stem`, `i_stem`, `u_stem`, `consonant_stem`, `e_stem`, `ia_stem`, `nasal_infix`, `sta_stem` |
| `ablaut_grade` | `e_grade`, `o_grade`, `zero_grade`, `lengthened_grade` |
| `derivation` | `root_formation`, `suffixal`, `prefixal`, `compound`, `deverbal`, `denominal`, `causative`, `iterative`, `inchoative`, `diminutive` |
| `stem_form` | `strong`, `weak` |
| `reduplication` | `reduplicated` |
| `verb_class` | `primary`, `secondary` |
| `accent_paradigm` | `ap1`, `ap2`, `ap3`, `ap4` |

Jei tinkamos reikšmės nėra, sukurk naują tokiu pat stiliumi.

```json
{"id": "f1", "feature": "inflection_class", "value": "athematic", "label": "atematinė forma",
 "applies_to": ["e1", "e2"], "provenance": "article", "confidence": null,
 "note": null, "evidence": "atematinės veiksmažodžių formos … esmi, esti"}
```

- `applies_to` – **vienintelė vieta**, kur objektas susiejamas su
  savybe. Viena savybė vienam straipsniui – vienas objektas su visais jos
  objektais; kurk atskirą tik jei skiriasi `provenance`.
- Gali būti ir `applies_to: []`, kai savybė minima apskritai (pvz. kad
  formos pakeistos tematinėmis, bet konkrečios tematinės formos neįvardytos).
- Paprastų kategorijų (asmuo, skaičius, laikas) čia nekartok – jos
  `morphology`.

## 7. Teiginiai: `claims`

Savarankiškai patikrinamas straipsnio (ar jame referuojamo autoriaus) teiginys.

```json
{"id": "c1", "type": "morphology", "status": "asserted", "stance": null,
 "text": "Senojoje lietuvių kalboje buvo atematinių formų, pvz. esmi, esti.",
 "about": ["f1", "e1", "e2"], "supports": [], "contradicts": [], "citations": ["s1"],
 "evidence": "Anksčiau gausios baltų kalbų atematinės veiksmažodžių formos …"}
```

- `type`: `etymology`, `reconstruction`, `sound_change`, `morphology`,
  `semantic_change`, `dating`, `attestation`, `comparison`, `cognacy`,
  `borrowing`, `derivation`, `analogy`, `folk_etymology`,
  `onomatopoeia`, `source_assessment`, `author_disagreement`, `warning`,
  `other`.
- `status`: `asserted`, `probable`, `possible`, `questioned`,
  `rejected`, `uncertain`, `alternative`, `reported_view`. Išsaugok
  autoriaus neapibrėžtumą („galbūt“, „vargu ar“ nėra faktai).
- `stance` – kai referuojama kito autoriaus nuomonė: `supports`,
  `rejects`, `questions`, `reports`, `prefers`, `neutral`; kitaip `null`.
- `about` – objektai (`e…`), savybės (`f…`), reikšmės (`m…`), grupės
  (`g…`), apie kuriuos teiginys kalba tiesiogiai.
- `supports` / `contradicts` – kitų teiginių ID, kuriuos šis teiginys
  paremia ar paneigia.
- Nekurk atskiro teiginio kiekvienam pavyzdžiui; atskirk konkuruojančias
  hipotezes ir atmestas analizes. Tavo paties išvadų teiginiais
  nepaversk (jos – `provenance: "llm_inference"` objektuose ir savybėse).

## 8. Etimologiniai ryšiai: `relations`

Tik istoriniai ir lyginamieji ryšiai tarp kalbinių objektų (ar tarp
savybių – `REPLACES`):

```json
{"type": "DESCENDS_FROM", "from": "e1", "to": "e4", "status": "probable",
 "claims": ["c2"], "provenance": "article", "confidence": null, "evidence": "..."}
```

`type`:

- `DESCENDS_FROM` – paveldėta iš ankstesnės formos / protoformos (vėlesnė → ankstesnė);
- `DERIVED_FROM` – vedinys iš pamato (vedinys → pamatas);
- `BORROWED_FROM` – skolinys (skolinys → donoras);
- `COGNATE_WITH` – giminiški atitikmenys, ne kilmė vienas iš kito;
- `COMPARED_WITH` – tik lyginama, giminystė neteigiama;
- `SOUND_CHANGE` – aiškiai tekste aprašyta garsų kaita (ankstesnė → vėlesnė);
- `REPLACES` – nauja forma ar klasė pakeitė seną (nauja → sena);
- `VARIANT_OF` – to paties žodžio variantas (tarminis, rašybos);
- `INFLUENCED_BY` – analogija, kontaminacija, sąveika.

Čia **nerašyk** lemos–formos, reikšmių, savybių ar teiginių tarpusavio
ryšių – jie turi savo laukus (3 skyrius).

## 9. Tekste cituojami šaltiniai: `citations`

```json
{"id": "s1", "raw": "Endzelīns 1971: 205–208", "author": "Endzelīns", "year": "1971",
 "locator": "205–208", "role": "discussion", "evidence": "aptarimą ir pavyzdžius žr. Endzelīns 1971: 205–208"}
```

Tik tai, kas matoma tekste; pavadinimų neatkurk iš atminties. `role`:
`supporting`, `opposing`, `discussion`, `data_source`, `other`.

## 10. `notes`

Tik etimologiškai svarbiai informacijai, kurios neįmanoma išreikšti
kitais laukais: `{"id": "n1", "title": "...", "text": "...", "evidence": "..."}`.

## 11. `paaiskinimas`

Paprasta lietuvių kalba paaiškink: ką teigia autorius, kokia pagrindinė
etimologinė mintis, kurios formos ar rekonstrukcijos svarbiausios,
kokios alternatyvos ir kodėl autorius vieną palaiko ar atmeta. Nepridėk
informacijos, kurios nėra tekste. Jei tekstas nutrūkęs ar per trumpas –
taip ir parašyk.

## 12. Įrodymai

`evidence` – trumpas, savarankiškai suprantamas teksto fragmentas (be
`⟨ ⟩`). `llm_inference` objektams jis gali būti `null`, bet tada
privalomas `confidence`, o savybėms – ir `note`.

## 13. Pavyzdys

Įvestis (straipsnio tekstas): „Anksčiau gausios baltų kalbų atematinės
veiksmažodžių formos (aptarimą ir pavyzdžius žr. Endzelīns 1971:
205–208), kaip senosios lietuvių kalbos ⟨esmi⟩, ⟨esti⟩, dabartinėse
baltų visos pakeistos tematinėmis.“ (antraštė `esmi`).

Atsakymas (sutrumpinta – `paaiskinimas` ir kai kurie laukai):

```json
{"entities": [
  {"id": "e1", "kind": "Form", "written": "esmi", "canonical": null, "language_text": "s. lie.",
   "language": "senoji lietuvių", "glottocode": "lith1251", "part_of_speech": "verb",
   "morphology": [{"category": "person", "value": "1"}, {"category": "number", "value": "singular"}, {"category": "tense", "value": "present"}],
   "lexeme_id": "e3", "homonym_no": null, "is_headword": true, "reconstruction": null,
   "provenance": "article", "confidence": null, "evidence": "senosios lietuvių kalbos esmi"},
  {"id": "e2", "kind": "Form", "written": "esti", "…": "…", "lexeme_id": "e3", "is_headword": false},
  {"id": "e3", "kind": "Lexeme", "written": "būti", "language": "lietuvių", "glottocode": "lith1251",
   "part_of_speech": "verb", "lexeme_id": null, "is_headword": false,
   "provenance": "llm_inference", "confidence": "high", "evidence": null}],
 "features": [
  {"id": "f1", "feature": "inflection_class", "value": "athematic", "label": "atematinė forma",
   "applies_to": ["e1", "e2"], "provenance": "article", "confidence": null, "note": null,
   "evidence": "baltų kalbų atematinės veiksmažodžių formos … kaip senosios lietuvių kalbos esmi, esti"},
  {"id": "f2", "feature": "inflection_class", "value": "thematic", "label": "tematinė forma",
   "applies_to": [], "provenance": "article", "confidence": null, "note": null,
   "evidence": "pakeistos tematinėmis"}],
 "claims": [
  {"id": "c1", "type": "morphology", "status": "asserted", "stance": null,
   "text": "Anksčiau baltų kalbose buvo daug atematinių veiksmažodžių formų, pvz. senosios lietuvių esmi, esti.",
   "about": ["f1", "e1", "e2"], "supports": [], "contradicts": [], "citations": ["s1"], "evidence": "…"},
  {"id": "c2", "type": "morphology", "status": "asserted", "stance": null,
   "text": "Dabartinėse baltų kalbose atematinės formos visos pakeistos tematinėmis.",
   "about": ["f1", "f2"], "supports": [], "contradicts": [], "citations": [], "evidence": "dabartinėse baltų visos pakeistos tematinėmis"}],
 "relations": [
  {"type": "REPLACES", "from": "f2", "to": "f1", "status": "asserted", "claims": ["c2"],
   "provenance": "article", "confidence": null, "evidence": "pakeistos tematinėmis"}],
 "citations": [
  {"id": "s1", "raw": "Endzelīns 1971: 205–208", "author": "Endzelīns", "year": "1971",
   "locator": "205–208", "role": "discussion", "evidence": "aptarimą ir pavyzdžius žr. Endzelīns 1971: 205–208"}]}
```

Atkreipk dėmesį: „atematinės / tematinės formos“ yra savybės, ne lemos;
tikroji lema `būti` pažymėta kaip tavo išvada; formos su savybe
susietos tik per `applies_to`; teiginiai rodo į savybes ir formas, o
straipsnis – tik į teiginius.

## 14. Patikra prieš atsakant

1. Ar kiekvienas `GUID` sutampa su įvesties straipsnio `GUID`?
2. Ar nėra `Lexeme`, kuris iš tikrųjų yra klasė, paradigma ar forma?
3. Ar kiekviena forma, kurios lema žinoma, turi `lexeme_id`?
4. Ar joks ryšys neaprašytas dviejose vietose (3 skyriaus lentelė)?
5. Ar visi `about`, `of`, `applies_to`, `members`, `supports`,
   `contradicts`, `citations`, `from`, `to` rodo į esamus to paties
   straipsnio ID?
6. Ar atskirta, ką sako straipsnis, o ką išvedei tu?
7. Ar iš objektų būtų galima atkurti straipsnio argumentaciją nepridedant
   naujų faktų?
