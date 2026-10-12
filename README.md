# outreach-sequencer

Comando Claude Code che prepara un piano di contatto per un ruolo target. **Prepara, non invia.**

## Uso
```
/outreach <URL o testo JD> | azienda, ruolo, città | nomi che conosco (opzionale)
```
Output: `plans/AAAA-MM-GG_azienda_ruolo.md` + una riga per persona in `tracker.csv`.

## Setup (una volta)
1. `cp templates/profile.template.md context/profile.md` e compila (CV, proof point con numeri esatti, legami verificati).
2. `cp templates/positioning.template.md context/positioning.md` e compila.
3. Netus MCP collegato (sola lettura finché non confermi).

## Pipeline
1. **JD** → priorità, seniority, fit. Seniority inferiore → `SKIP — seniority mismatch`, stop.
2. **CRM Netus** (lettura) → warm path esistenti.
3. **Mappa persone** (max 5): warm path → headhunter → hiring manager → recruiter. Nome non trovato → ricerca LinkedIn esatta da fare a mano.
4. **Messaggi**: nota ≤300 caratteri, messaggio ≤120 parole, intro inoltrabile per i warm path.
5. **Cadenza**: D0, D+5 (valore), D+12 (chiusura).
6. **Controlli** automatici: `python3 scripts/lint_plan.py lint|track|check-context`.
7. **Scrittura su Netus solo dopo tuo "sì"**; interazioni registrate solo quando hai davvero inviato.

## File
| Percorso | Ruolo |
|---|---|
| `.claude/commands/outreach.md` | il comando |
| `context/` | profilo e posizionamento (tuoi, non tracciati) |
| `templates/` | piano, schemi messaggi, template profilo |
| `plans/`, `tracker.csv` | output (non tracciati) |
| `scripts/lint_plan.py` | limiti di lunghezza, struttura, proof point, tracker |

## Privacy
Questo repo pubblica un sito (GitHub Pages): `.gitignore` esclude dati personali, ma gli output restano solo nel container/sul disco locale. Per backup e versioning sposta il tool in un **repo privato**.

## Stati tracker
`da contattare` → `inviato` → `follow-up 1` → `follow-up 2` → `risposto` | `chiuso`
