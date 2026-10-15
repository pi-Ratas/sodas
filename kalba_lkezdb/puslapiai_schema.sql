BEGIN TRANSACTION;
CREATE TABLE IF NOT EXISTS "puslapiai" (
	"GUID"	TEXT NOT NULL,
	"LKEZDB_Zodis"	TEXT NOT NULL,
	"LKEZDB_atsakymas"	TEXT,
	"zmogiskas_paaiskinimas"	TEXT,
	"grafo_importo_planas"	TEXT,
	"semantinis_json"	TEXT,
	"llm_atsakymas"	TEXT,
	"aiskinimo_uzklausa"	TEXT,
	PRIMARY KEY("GUID"),
	FOREIGN KEY("LKEZDB_Zodis") REFERENCES "zodziai"("GUID") ON UPDATE CASCADE ON DELETE RESTRICT
);
CREATE TABLE IF NOT EXISTS "saltiniai" (
	"GUID"	TEXT,
	"santrumpa"	TEXT NOT NULL,
	"saltinis"	TEXT NOT NULL,
	PRIMARY KEY("GUID")
);
CREATE TABLE IF NOT EXISTS "straipsniai" (
	"GUID"	TEXT NOT NULL,
	"LKEZDB_Puslapis"	TEXT NOT NULL,
	"antraste"	TEXT,
	"reiksme"	TEXT,
	"istrauka"	TEXT,
	"saltinis"	TEXT,
	"metai"	TEXT,
	"vieta_saltinyje"	TEXT,
	"patikimumas"	TEXT,
	"pastaba"	TEXT,
	"zmogiskas_paaiskinimas"	TEXT,
	"grafo_importo_planas"	TEXT,
	"semantinis_json"	TEXT,
	PRIMARY KEY("GUID"),
	FOREIGN KEY("LKEZDB_Puslapis") REFERENCES "puslapiai"("GUID") ON UPDATE CASCADE ON DELETE RESTRICT
);
CREATE TABLE IF NOT EXISTS "straipsniu_nuorodos" (
	"straipsnio_GUID"	TEXT,
	"puslapio_GUID"	TEXT,
	PRIMARY KEY("straipsnio_GUID","puslapio_GUID")
);
CREATE TABLE IF NOT EXISTS "zodziai" (
	"GUID"	TEXT NOT NULL UNIQUE,
	"nuskaityta"	BOOLEAN DEFAULT 0,
	"zodis"	TEXT NOT NULL,
	"url"	TEXT NOT NULL UNIQUE,
	"puslapio_GUID"	TEXT,
	"isaiskinta"	BOOLEAN DEFAULT 0,
	"itraukta"	BOOLEAN DEFAULT 0,
	PRIMARY KEY("GUID")
);
CREATE TABLE IF NOT EXISTS "zodzio_aiskinimai" (
	"GUID"	TEXT NOT NULL,
	"zodzio_GUID"	TEXT NOT NULL,
	"puslapio_GUID"	TEXT NOT NULL,
	"numeris"	INTEGER NOT NULL,
	"grafo_importo_planas"	TEXT NOT NULL,
	"semantinis_json"	TEXT NOT NULL,
	"llm_atsakymas"	TEXT,
	"aiskinimo_uzklausa"	TEXT,
	"grafo_importo_hash"	TEXT,
	"itraukta"	INTEGER NOT NULL DEFAULT 0,
	"sukurta"	TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
	"atnaujinta"	TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
	PRIMARY KEY("GUID"),
	UNIQUE("zodzio_GUID"),
	FOREIGN KEY("zodzio_GUID") REFERENCES "zodziai"("GUID") ON UPDATE CASCADE ON DELETE CASCADE,
	FOREIGN KEY("puslapio_GUID") REFERENCES "puslapiai"("GUID") ON UPDATE CASCADE ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS "neo4j_import_log" (
	"computer_id"	TEXT NOT NULL,
	"explanation_id"	TEXT NOT NULL,
	"plan_hash"	TEXT NOT NULL,
	"imported_at"	TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
	"status"	TEXT NOT NULL DEFAULT 'done',
	"klaida"	TEXT,
	PRIMARY KEY("computer_id","explanation_id"),
	FOREIGN KEY("explanation_id") REFERENCES "zodzio_aiskinimai"("GUID") ON UPDATE CASCADE ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS "idx_neo4j_import_log_computer_status_hash"
ON "neo4j_import_log"("computer_id","status","plan_hash");
CREATE TABLE IF NOT EXISTS "analizes_darbai" (
	"GUID"	TEXT NOT NULL,
	"zodzio_GUID"	TEXT NOT NULL,
	"busena"	TEXT NOT NULL DEFAULT 'pending',
	"auto_itraukti"	INTEGER NOT NULL DEFAULT 1,
	"klaida"	TEXT,
	"rezultatas"	TEXT,
	"sukurta"	TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
	"pradeta"	TEXT,
	"baigta"	TEXT,
	"atnaujinta"	TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
	PRIMARY KEY("GUID"),
	FOREIGN KEY("zodzio_GUID") REFERENCES "zodziai"("GUID") ON UPDATE CASCADE ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS "idx_analizes_darbai_busena_sukurta"
ON "analizes_darbai"("busena","sukurta");
CREATE TABLE IF NOT EXISTS "uzklausos" (
	"GUID"	TEXT NOT NULL,
	"pavadinimas"	TEXT NOT NULL,
	"turinys"	TEXT NOT NULL,
	"sukurta"	TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
	"atnaujinta"	TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
	PRIMARY KEY("GUID")
);
CREATE TABLE IF NOT EXISTS "app_nustatymai" (
	"raktas"	TEXT NOT NULL,
	"reiksme"	TEXT,
	PRIMARY KEY("raktas")
);
COMMIT;
