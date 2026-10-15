# Sodas

*[Lietuviškai](README.lt.md)*

**Sodas** (Lithuanian for *orchard, garden*) is a tool for linguists: it brings public linguistic datasets (Glottolog,
Concepticon, IE-CoR, CLICS, WALS and others) together into one Neo4j graph and lets you explore it in the browser.

- **Land** (Žemė) – the datasets the gardens grow from: download them and import them into Neo4j; **LKEŽDB** (optional) –
  explaining entries of the Lithuanian Etymological Dictionary Database with a language model.
- **Garden** – explore the graph: search, "plant" nodes and relationships, merging identical nodes, bundles, shortest paths,
  map, a research basket, your own relationships (Ctrl+J); download a garden (SVG, PNG, JSON) together with its bibliography.
- **Vaiva** – studies on the basket's nodes: spectral clustering of forms by sound similarity, lexical closeness of
  languages vs. the genealogical tree, semantic stability of concepts; the **workshop** – build your own study from parts.
- **Bibliography** – every garden and study remembers which datasets it used; 📚 gives their citations and Sodas's own
  (BibTeX, BibLaTeX, RIS, CSL-JSON, APA).

Sodas runs on your own computer: it starts a small local server and you work in the browser at `http://127.0.0.1:8765/`.
The interface is available in 15 languages (the button at the top right). On the first visit to the garden a short lesson is
offered (start it again any time from the SODAS sign at the top left).

---

## Requirements

| | |
|---|---|
| Operating system | Linux, macOS or Windows 10/11 (developed and tested on Linux) |
| Python | 3.10 or newer |
| Neo4j | 5 or newer (Community edition is free; no plugins needed) |
| Memory | 8 GB is enough for a few datasets; all 14 (CLICS4 above all) need 32 GB or more |
| Disk | ~1.5 GB for the datasets; up to a few tens of GB for import files (`build/`) and the Neo4j store when importing everything |
| Internet | to download the datasets (once) and for map tiles |

---

## Installation

### 1. Neo4j

- **Easiest (all systems):** [Neo4j Desktop](https://neo4j.com/download/). Create a new *Local DBMS*, choose a password, press **Start**.
- **Linux server:** [Neo4j Community Server](https://neo4j.com/docs/operations-manual/current/installation/linux/).
  Set the password once: `sudo neo4j-admin dbms set-initial-password <password>`, then `sudo systemctl start neo4j`.
- **Docker:**
  ```bash
  docker run -d --name sodas-neo4j -p 7474:7474 -p 7687:7687 -e NEO4J_AUTH=neo4j/<password> neo4j:5
  ```

<http://localhost:7474> should open the Neo4j Browser. For large imports give Neo4j more memory in `neo4j.conf`
(e.g. `server.memory.heap.max_size=4G`, `server.memory.pagecache.size=4G`).

### 2. Python

- **Linux:** usually present; on Debian/Ubuntu also `sudo apt install python3-venv`.
- **macOS:** `brew install python` or [python.org](https://www.python.org/downloads/).
- **Windows:** [python.org](https://www.python.org/downloads/); tick **"Add python.exe to PATH"** in the installer.

### 3. Sodas

Download it (**Code → Download ZIP** on GitHub, then unzip) or clone it:

```bash
git clone https://github.com/pi-Ratas/sodas.git
cd sodas
```

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

### 4. Connection to Neo4j

Copy `neo4j.example.yaml` to `neo4j.yaml` and put your Neo4j password in it:

```yaml
neo4j:
  uri: bolt://localhost:7687
  user: neo4j
  password: <your password>
  database: neo4j
```

(Environment variables `KALBA_NEO4J_URI`, `KALBA_NEO4J_USER`, `KALBA_NEO4J_PASSWORD`, `KALBA_NEO4J_DATABASE` work too.)

### 5. Start

From the Sodas folder, with `.venv` active:

```bash
sodas
```

The browser opens at `http://127.0.0.1:8765/`; `Ctrl+C` in the terminal stops it. Settings, gardens, uploaded pictures, the
list of relationships drawn in the garden, Vaiva studies and the log are kept in `sodas-duomenys/` (for a backup copy it and
the Neo4j database).

---

## Datasets: download and import

The datasets are **not** shipped with Sodas – everyone downloads them. Sodas knows which release of each dataset to fetch:
the one it was tested with (a GitHub archive; `git` is not needed).

1. In the top bar open **Žemė** (tab "Datasets").
2. **⭳ Download all missing** (~1.3 GB) or **⭳ Download** next to a dataset. They are unpacked into `duomenynai/`.
3. Tick the datasets and press **Import the selected**. Authorities a dataset needs (Glottolog, Concepticon) are suggested.
4. After importing: **Link to authorities**.
5. Back in the **Garden**, search (e.g. *Lithuanian*, *moon*).

**To begin with:** Glottolog, Concepticon, CLTS and IE-CoR – enough for every Vaiva study except semantic stability
(which also needs DatSemShift).

From the command line:

```bash
kalba-import download --list
kalba-import download --only glottolog,concepticon,clts,iecor
kalba-import import-all --config datasets.yaml --only glottolog,concepticon,clts,iecor
kalba-import resolve
```

`datasets.yaml` says where each dataset lives; point it to your own copy if you have one.

### Dataset licences

The data are not part of Sodas. Most datasets are **CC BY 4.0**; **D-PLACE** and **NoRaRe** are **CC BY-NC 4.0**
(non-commercial). Please cite the datasets you use (see "source ↗" next to each dataset). Versions: Glottolog v5.3,
Concepticon v3.4.0, CLTS v2.3.0, IE-CoR v1.2, WOLD v4.2, Lexibank v2.2.6, CLICS4 v1.0, NoRaRe v1.1, PHOIBLE v2.0.1,
WALS v2020.5, Grambank v1.0.3, D-PLACE v3.2.0, ASJP v21.1, DatSemShift v1.1rc.

---

## LKEŽDB (optional)

**Žemė → LKEŽDB** needs the LKEŽDB data cache `duomenynai/lkezdb/puslapiai.db`, which is **not** distributed with Sodas,
and an OpenAI (or compatible) API key – see [docs/OpenAI_raktas.md](docs/OpenAI_raktas.md). Without them only this
section is unavailable.

## Troubleshooting

- **"Neo4j is not reachable" / "password not set"** – is Neo4j running (<http://localhost:7474>)? Is `neo4j.yaml` in the
  Sodas folder? Run `sodas` from that folder.
- **A download stopped** – press it again; an unfinished download never leaves a half-filled folder.
- **Import ran out of memory** – import one dataset at a time (CLICS4 is the largest); give Neo4j more memory.
- **Port 8765 is busy** – `sodas --port 8780`.

The full guide (in Lithuanian): [docs/vadovas.md](docs/vadovas.md).

## Licence and citation

© 2026 Kęstutis Račkaitis. The code is licensed under the **GNU Affero General Public License v3.0** ([LICENSE](LICENSE)):
use, change and share it freely; modified versions – including ones offered as a network service – must stay open under
the same licence.

Bundled third-party code: [Cytoscape.js](https://js.cytoscape.org/) (MIT), [Leaflet](https://leafletjs.com/) (BSD-2-Clause);
flag images from [flag-icons](https://github.com/lipis/flag-icons) (MIT).

If Sodas helped your research, please cite it ([CITATION.cff](CITATION.cff); "Cite this repository" on GitHub). In the
program the citation is behind the SODAS sign, and the bibliography of a garden or a study (Sodas and every dataset used) behind
📚. The "About Sodas" window shows the author's contacts from `kontaktai.yaml`.
