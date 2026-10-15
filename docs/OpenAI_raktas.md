# OpenAI API raktas (tik LKEŽDB skilčiai)

Raktas reikalingas **tik** LKEŽDB žodžių aiškinimui kalbos modeliu (⚙ → LKEŽDB). Sodas, Vaiva ir duomenynų importas veikia be jo.
Kalbos modelio užklausos yra mokamos (OpenAI sąskaita).

Raktas laikomas byloje **`.raktas`** Sodo aplanke (ten, iš kur paleidžiate `sodas`). Byla į git nepatenka (`.gitignore`).

1. [platform.openai.com](https://platform.openai.com) → **API keys** → **Create new secret key**. Patikrinkite, kad projekte yra kreditų (Billing).
2. Raktą (prasideda `sk-`) įrašykite į `.raktas` – vieną eilutę, be tarpų ir kabučių.

   Linux / macOS (raktas neliks komandų istorijoje):

   ```bash
   read -rsp 'Raktas: ' R; echo; printf '%s\n' "$R" > .raktas; unset R; chmod 600 .raktas
   ```

   Windows: sukurkite bylą `.raktas` Užrašinėje (Notepad) ir įrašykite raktą.
3. Patikrinkite: `python -m kalba_lkezdb raktas --tikrinti`.

Vietoje bylos galima naudoti aplinkos kintamąjį `OPENAI_API_KEY`. Tinka ir kitas OpenAI suderinamas API (pvz. vietinis LM Studio):
⚙ → LKEŽDB → „Variklis ir užklausa“.
