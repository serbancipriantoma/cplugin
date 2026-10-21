# cplugin: specificație

> Ciornă v0.1, 2026-10-21. `cplugin` e numele de lucru; numele final schimbă și comenzile (`/cplugin:...`) și folderul de stare (`.cplugin/`).
> Pornește de la plugin-ul playbook 1.4.7. Secțiunea 12 spune ce preluăm și ce schimbăm.

## 1. Scop

Un plugin pentru Claude Code care:

1. ține **memoria proiectului** în două niveluri: ideile mari în `MIND_MAP.md` și detaliile, pe module, în fișiere mici;
2. face orice modificare de cod printr-un **task** (`task.md`), parcurs în etape care se bifează pe rând;
3. împarte munca între agenți cu **roluri stricte**: MAIN coordonează, worker scrie cod, tester scrie teste, iar judges evaluează;
4. pune **judges de la alți furnizori** (Codex, Antigravity) să verifice ce a scris Claude;
5. arată live, într-un **tablou ASCII**, ce agent lucrează și la ce;
6. impune regulile prin **hook-uri** care blochează abaterile, nu doar avertizează.

## 2. Memoria proiectului

### 2.1 Două niveluri

| Fișier | Conține | Când se citește |
|---|---|---|
| `MIND_MAP.md` | Ideile mari: un nod numerotat pe modul, 3–6 rânduri fiecare, și link spre detalii | Automat, la începutul fiecărei sesiuni (hook-ul SessionStart) |
| `mindmap/<modul>.md` | Ce face fiecare secțiune a modulului: reguli, date, cazuri limită, unde e codul, unde sunt testele, decizii luate | La cerere, când un task atinge modulul. E prima etapă din Design |

`MIND_MAP.md` trebuie să rămână sub **8.500 de caractere**, pentru că intră în context la fiecare pornire, iar Claude Code taie la 10.000 de caractere textul injectat de un hook. Dacă îl depășește, hook-ul încarcă doar începutul și îi cere lui Claude să citească restul și să-ți spună că harta trebuie comprimată. Ce e mai detaliat se mută în `mindmap/`.

### 2.2 Exemplu

`MIND_MAP.md`:

```markdown
# MIND_MAP — Clinica

## [1] Prezentare
Aplicație pentru gestiunea unei clinici. Module: [2] Pacient, [3] Medic, [4] Facturare.

## [2] Pacient → mindmap/pacient.md
- Face consultații: cu un medic [3], rezultatul intră în dosar
- Face programări: alege un slot liber, primește confirmare, poate anula
- Accesează dosarul pacientului: istoric, analize, rețete
```

`mindmap/pacient.md`:

```markdown
# Pacient — detalii
Rezumat: MIND_MAP [2]

## Consultații
- Ce face: ...
- Reguli: ...
- Cod: src/pacient/consultatii.py
- Teste: tests/pacient/test_consultatii.py
- Decizii: (task 012) consultația nu se poate șterge, doar anula

## Programări
...

## Dosarul pacientului
...
```

### 2.3 Reguli

- Fiecare nod din `MIND_MAP.md` care are detalii indică fișierul lor (`→ mindmap/<modul>.md`).
- Un fișier de detalii are câte o secțiune `##` pentru fiecare parte a modulului. Dacă depășește ~400 de rânduri, se împarte în `mindmap/<modul>/<secțiune>.md`.
- La finalul fiecărui task, **fișierul de detalii se actualizează pe loc**, în secțiunea care se ocupă de partea respectivă. `MIND_MAP.md` se modifică doar dacă s-au schimbat ideile mari. Nu se adaugă câte un nod nou pentru fiecare task (lecție preluată din playbook).
- `/cplugin:mindmap` generează prima versiune din codul existent. Pe un proiect nou, o completăm împreună din discuție.

## 3. Task-ul

### 3.1 Unde stă și cum se creează

- `.cplugin/tasks/<NNN>-<tip>-<nume>/task.md`, plus subfolderul `judges/` pentru rapoartele judges.
- Se creează **doar** cu `tasks new <tip> <nume> --modul <modul>`. Hook-ul blochează crearea manuală.
- Tipuri: `feature`, `bugfix`, `refactor`, `explore`, `test`, `docs`.
- `tasks work <N>` activează task-ul, `tasks done` îl închide și refuză dacă mai sunt etape nebifate. `tasks stop` îl dezactivează fără să-l închidă. `tasks list` și `tasks status` arată starea.
- `tasks pause "<motiv>"` îi permite lui MAIN să-și încheie tura cu etape deschise, când are nevoie de tine.
- Starea stă pe disc, nu în conversație. De aceea task-ul supraviețuiește compactării contextului și poate fi reluat în altă sesiune.

### 3.2 Etapele

| # | Etapă | Cine | Ce se întâmplă |
|---|---|---|---|
| 1 | **Design** | MAIN | Citește detaliile modulului. Spune cu vorbele lui ce i s-a cerut, cum arată „gata” (criterii verificabile), ce intră și ce nu intră în task |
| 2 | **Plan Review** | judges, apoi MAIN | Judges evaluează planul fără să vadă conversația și fără să poată modifica ceva. MAIN acceptă, amână sau respinge fiecare observație, cu motiv |
| 3 | **Work Plan** | MAIN, tester, worker | Pentru fiecare pas: teste → teste roșii → implementare → teste verzi (secțiunea 4.3) |
| 4 | **Implementation Review** | judges, apoi MAIN | Judges evaluează codul (diff-ul task-ului). MAIN triază observațiile la fel ca la etapa 2 |
| 5 | **Review final** | MAIN | Testele trec, nu au rămas urme de debug, iar `mindmap/<modul>.md` (și `MIND_MAP.md`, dacă e cazul) e actualizat |

### 3.3 Șablonul `task.md`

```markdown
# 007 — feature — programari-pacient

## Status
activ

## Cerința
(textul tău, copiat exact de `tasks new`)

## Context
- MIND_MAP: [2] Pacient
- Detalii: mindmap/pacient.md → Programări

## 1. Design
- [ ] Am citit secțiunile afectate din mindmap/pacient.md: ...
- [ ] Cererea, cu vorbele mele: ...
- [ ] „Gata” înseamnă (criterii verificabile): ...
- [ ] Intră în task: ...
- [ ] Nu intră în task: ...

## 2. Plan Review
- [ ] `tasks plan-review 7`
- [ ] Triere: fiecare observație → acceptat / amânat / respins + motiv

## 3. Work Plan
(câte un grup pe pas, completat la Design)
### Pas 1: <ce se implementează>
Criterii: ...
Interfață: ...
Verificare: teste            (sau: manual — <verificare concretă>)
- [ ] Teste (tester): ...
- [ ] Roșu: testele pică din motivul corect (comanda + câte pică)
- [ ] Implementare (worker): ...
- [ ] Verde: comanda + câte trec
- [ ] Checkpoint: ce n-am anticipat? Planul mai e bun?

## 4. Implementation Review
- [ ] `tasks impl-review 7`
- [ ] Triere: fiecare observație → acceptat / amânat / respins + motiv

## 5. Review final
- [ ] Toate testele trec (comanda + numărul de teste)
- [ ] Fără urme de debug
- [ ] mindmap/pacient.md actualizat pe loc; MIND_MAP.md doar dacă s-au schimbat ideile mari

## Amânate
(ce a apărut pe parcurs și nu intră aici, cu destul context pentru un task viitor)
```

Regula de bifare: o etapă bifată primește pe același rând un rezultat scurt. Textul original nu se înlocuiește. Planul se poate modifica pe parcurs, dar doar prin etape nebifate.

## 4. Agenții

### 4.1 Roluri

| Rol | Ce e | Model (implicit) | Scrie în | Nu are voie |
|---|---|---|---|---|
| **MAIN** | Sesiunea principală, cea cu care vorbești | ce rulezi tu | `task.md` (task-ul activ), `MIND_MAP.md`, `mindmap/**` | să scrie cod sau teste: deleagă |
| **worker** | Sub-agent Claude (`agents/worker.md`) | `opus` | fișierele de cod din `roles.worker.paths` | să scrie teste, să bifeze etape, să pornească alți agenți, să ruleze `tasks` |
| **tester** | Sub-agent Claude (`agents/tester.md`) | `sonnet` | fișierele de test din `roles.tester.paths` | să scrie cod, să bifeze etape, să pornească alți agenți, să ruleze `tasks` |
| **judge** | CLI extern: `codex`, `agy` | modelul implicit al CLI-ului | nimic: rulează în sandbox read-only | orice modificare |

- Sub-agenții **nu văd conversația**: primesc doar ce le dă MAIN în prompt (pasul, criteriile, fișierele relevante), plus `CLAUDE.md`.
- worker și tester nu au tool-ul `Agent` (`disallowedTools` în frontmatter), deci nu pot porni alți agenți.
- Doar MAIN bifează etapele. worker și tester întorc un raport, iar MAIN îl rezumă în `task.md`.
- Fișierele care nu sunt cod (`.md`, `.json`, `.yaml`, imagini) nu sunt restricționate pe roluri. „Cod” se definește ca în playbook: după extensie, plus `bin/`, `scripts/` și fișierele care încep cu shebang. Lista e configurabilă.

### 4.2 Cum se impun rolurile

Hook-ul PreToolUse primește `agent_type` când apelul vine dintr-un sub-agent. Dacă lipsește, apelul e al lui MAIN. Pentru fiecare Edit/Write/NotebookEdit:

1. află rolul din `agent_type` (`cplugin:worker`, `cplugin:tester`, sau lipsă = MAIN);
2. compară calea fișierului cu căile permise rolului în `config.toml`;
3. dacă nu e permisă, oprește apelul cu `permissionDecision: "deny"` și un mesaj care spune cui îi aparține fișierul.

Bash nu poate fi controlat pe căi înainte de execuție (`echo > x.py` trece). De aceea, după fiecare Bash, PostToolUse compară `git status` cu instantaneul anterior. Dacă rolul a modificat fișiere care nu-i aparțin, agentul primește imediat un mesaj, iar abaterea se notează în `task.md`, la secțiunea „Abateri”. Asta presupune ca proiectul să fie un repo git.

### 4.3 Un pas din Work Plan

**Teste înainte de cod** (implicit, decis 2026-10-21):

```
MAIN: Pas 3. Criterii: "un cavaler lovește un arcaș: daună 6–9, redusă de apărare"
      Interfață: damage(attacker, defender, rng) -> int
  └─► tester  primește DOAR criteriile + interfața și scrie testele
MAIN: rulează testele → trebuie să PICE (Roșu)
  ├─ pică din motivul corect (lipsește funcționalitatea) → continuă
  ├─ pică din alt motiv (eroare de sintaxă, import greșit) → înapoi la tester
  └─ trec deja → nu testează nimic nou → înapoi la tester
  └─► worker  primește criteriile + interfața + calea testelor; implementează până trec
MAIN: rulează testele → Verde
  └─ dacă worker-ul spune că un test e greșit: MAIN decide cine are dreptate
     și notează motivul în task.md (test greșit → tester; cod greșit → worker)
MAIN: Checkpoint
```

- Tester-ul lucrează **orb** prin construcție, pentru că codul nu există încă. Testele verifică ce s-a cerut, nu ce s-a scris.
- **Roșu** dovedește că testele chiar testează ceva nou. În paralel nu s-ar putea verifica asta.
- Worker-ul nu poate modifica teste, iar tester-ul nu poate modifica cod. Așa, un eșec nu se poate „repara” slăbind partea celuilalt.
- Interfața o fixează MAIN la Design, nu tester-ul. Altfel tester-ul ar decide singur cum arată API-ul.
- Riscul de cod scris „pentru teste”, adică exact ce trece testele și nu ce s-a cerut, îl prinde Implementation Review, unde judges compară codul cu cerința.
- **Pașii care nu se pot testa automat** (grafică, animații, senzația de joc) au `Verificare: manual — <verificare concretă>`. În locul etapelor Teste/Roșu/Verde au o etapă „Verificare manuală”, cu rezultatul.
- Cu `workflow.tests_first = false`, tester-ul și worker-ul pornesc în paralel, ca în varianta inițială, iar etapa Roșu dispare.

### 4.4 Configurarea: un singur fișier

`.cplugin/config.toml` se commite și se poate edita de mână. A fost ales TOML pentru că acceptă comentarii și Python îl citește fără dependențe (`tomllib`).

```toml
[workflow]
tests_first = true                  # false = tester și worker în paralel, fără etapa Roșu

[roles.worker]
model = "opus"                      # opus | sonnet | haiku | fable | ID complet
paths = ["src/**", "app/**"]        # unde are voie să scrie
max_parallel = 1                    # câți worker simultan

[roles.tester]
model = "sonnet"
paths = ["tests/**", "**/test_*.py", "**/*.test.*", "**/*.spec.*"]

[roles.main]
paths = ["MIND_MAP.md", "mindmap/**"]   # task.md-ul activ e permis mereu

[judges]
mode = "panel"          # single = primul judge disponibil; panel = toți, în paralel
timeout_min = 15
fallback = "claude"     # dacă niciun CLI extern nu merge: sub-agent Claude read-only; "none" = eroare

[[judges.seat]]
provider = "codex"
model = ""              # gol = modelul implicit al CLI-ului

[[judges.seat]]
provider = "agy"
model = ""

[tests]
command = "pytest -q"

[review]
debug_patterns = ["print(", "console.log(", "debugger", "breakpoint()"]
```

- MAIN citește modelul fiecărui rol din config și îl transmite când pornește sub-agentul. Pentru a schimba modelul nu se editează plugin-ul.
- Prompturile de rol stau în plugin (`agents/*.md`). Pentru reguli specifice proiectului, adaugi `.cplugin/roles/<rol>.md`. MAIN îl include în promptul sub-agentului.
- `tasks config check` validează fișierul: căile tester/worker nu se suprapun, CLI-urile judges există, comanda de test există.

## 5. Judges

- Le pornește `tasks plan-review <N>` sau `tasks impl-review <N>`, rulat de MAIN.
- Fiecare judge primește `task.md` (fără triere), `MIND_MAP.md`, fișierul de detalii al modulului și acces de citire la repo. La impl-review primește și diff-ul task-ului. Conversația n-o primește niciodată.
- Rulează **read-only**: Codex cu propriul sandbox read-only, iar orice alt CLI prin `sandbox-exec` (macOS), cu un profil care interzice scrierea în proiect. În plus, CLI-ul face o verificare de modificare: compară `git status` și hash-ul `task.md` înainte și după. Dacă un judge a schimbat ceva, raportul se marchează cu TAMPER, nu se folosește, iar comanda iese cu eroare (idee preluată din playbook).
- Raportul fiecărui judge se scrie în `judges/<etapă>-<provider>.md`, iar rezumatul în `task.md`. Le scrie CLI-ul, nu judge-ul.
- Adaptoarele pentru Codex și Antigravity pornesc de la cele din playbook (`provider/adapters/codex.py`, `antigravity.py`). Pe mașina asta sunt instalate `codex` 0.156.1 și `agy` 1.2.9.

## 6. Hook-uri

| Eveniment | Ce face |
|---|---|
| **SessionStart** (`startup`, `resume`, `clear`, `compact`) | Înregistrează sesiunea (ID-ul din payload, procesul Claude care o rulează și `CPLUGIN_SESSION_ID`, prin `CLAUDE_ENV_FILE`). Creează `.claude/bin/` (`tasks`, `board`, `sandbox`). Șterge sesiunile moarte. După `/clear`, dacă ID-ul s-a schimbat, preia task-ul activ al sesiunii anterioare din același proces. **Bagă în context `MIND_MAP.md` și starea task-ului activ** (etapa curentă) |
| **PreToolUse** (`Edit\|Write\|NotebookEdit\|Bash\|Agent`) | Blochează codul fără task activ. Impune rolurile (4.2). Blochează crearea manuală a task-urilor. Blochează bifarea a 3+ etape deodată, iar la 2 avertizează. Blochează `tasks …` rulat din sub-agenți. Notează acțiunea în tablou |
| **PostToolUse** (toate) | Doar pentru MAIN: arată etapa curentă (`fișier:linie`) și o întrebare de verificare care depinde de ce a făcut („Is this the simplest change that works?”, „Did it pass for the right reason?”). Pentru sub-agenți face doar verificarea Bash (4.2) și actualizează tabloul |
| **SubagentStart** | Trece agentul ca activ în tablou. Îi adaugă în context regulile rolului și pasul curent |
| **SubagentStop** | Trece agentul ca terminat în tablou |
| **Stop** | Nu-l lasă pe MAIN să termine cât timp sunt etape nebifate. Excepții: tura a fost doar conversație (0 scrieri și <5 tool-uri de la ultimul Stop), MAIN a rulat `tasks pause "<motiv>"` pentru că are nevoie de tine (o decizie, un răspuns, o verificare manuală), modul freehand, sau `stop_hook_active` (ca să nu intre în buclă) |
| **SessionEnd** | Notează că sesiunea s-a închis, dar **nu șterge starea**. `claude --continue` păstrează același ID de sesiune (verificat), deci task-ul activ trebuie să supraviețuiască repornirii. Sesiunile se șterg abia când procesul lor nu mai există și n-au mai fost folosite de 7 zile |

Principii, preluate din problemele playbook:

- un hook nu are voie să dărâme sesiunea: la eroare internă nu blochează nimic, cu o singură excepție, regula „fără task activ”, care blochează și când hook-ul nu știe sigur;
- hook-urile sunt scrise în Python (stdlib, ≥3.11), cu un singur punct de intrare (`hooks/run.py <eveniment>`), nu în bash care cheamă Python de 5 ori pe apel;
- curățarea sesiunilor nu urmează niciodată link-uri simbolice.

## 7. Tabloul ASCII

```
┌ TASK 007 · programari-pacient ─ etapa 9/18 ───────────────┐
│ Pas 2: POST /programari                                   │
├─────────┬───────────┬─────────────────────────────────────┤
│ MAIN    │ ● așteaptă│ worker, tester                      │
│ worker  │ ● Edit    │ src/programari/service.py      0:42 │
│ tester  │ ● Write   │ tests/test_programari.py       0:38 │
│ judge   │ ○ —       │                                     │
└─────────┴───────────┴─────────────────────────────────────┘
```

- Starea se scrie în `.cplugin/sessions/<id>/board.json` de hook-uri (SubagentStart/Stop, PreToolUse) și de CLI (judges care rulează, cu timpul scurs).
- `.claude/bin/board --watch` se rulează într-un al doilea terminal și se reîmprospătează la ~1s. Fără argumente arată sesiunea activă a proiectului, iar cu `--session` o alegi.
- Câte un rând pentru fiecare agent pornit. Dacă rulează doi worker în paralel, apar două rânduri.
- `/cplugin:board` afișează același tablou o dată, în chat.

## 8. Freehand și sandbox

- **`/cplugin:freehand`**: suspendă blocajele (fără task, roluri, Stop) până la următorul `tasks work`. Tabloul arată „FREEHAND”. Ce s-a modificat se notează la reactivare, ca să nu se piardă.
- **`.claude/bin/sandbox`**: pornește `claude --dangerously-skip-permissions` sub `sandbox-exec`. Poate scrie doar în proiect, `.git` e read-only, iar restul sistemului e blocat. Dacă `sandbox-exec` lipsește, **refuză să pornească**, în loc să ruleze neizolat (playbook doar avertiza).

## 9. Structura plugin-ului

```
cplugin/
├── .claude-plugin/
│   ├── plugin.json
│   └── marketplace.json        # marketplace local, pentru instalare
├── agents/
│   ├── worker.md
│   ├── tester.md
│   └── judge.md                # rezervă Claude, doar Read/Grep/Glob
├── skills/                     # /cplugin:<nume>. Skills, nu commands/ (recomandarea actuală)
│   ├── init/  mindmap/  freehand/  board/
│   └── workflow/SKILL.md       # cum coordonează MAIN un task
├── hooks/
│   ├── hooks.json
│   └── run.py                  # punct unic de intrare pentru toate hook-urile
├── cplugin/                    # pachetul Python: tasks CLI, config, roluri, tablou, judges
├── templates/                  # task.md, MIND_MAP.md, mindmap-module.md, CLAUDE.md, config.toml
├── bin/                        # tasks.py, board.py, sandbox: puncte de intrare
└── tests/                      # unittest stdlib; hook-urile testate cu JSON de intrare
```

## 10. Un proiect după `/cplugin:init`

```
proiect/
├── CLAUDE.md                   # secțiune scurtă: workflow + comenzi
├── MIND_MAP.md
├── mindmap/
├── .cplugin/
│   ├── config.toml             # se commite
│   ├── roles/                  # opțional: reguli de rol pentru proiect
│   ├── tasks/                  # se commite: istoria deciziilor
│   └── sessions/               # stare runtime, în .gitignore
└── .claude/
    ├── bin/                    # tasks, board, sandbox
    └── settings.json           # deny: TodoWrite, EnterPlanMode; playbook dezactivat aici
```

`init` e idempotent: rulat din nou, actualizează secțiunile plugin-ului și nu atinge restul. Dacă proiectul nu e repo git, propune `git init`.

## 11. Limitări cunoscute și lucruri de verificat în prototip

- **Același `session_id` în sub-agenți?** Documentația nu spune. Trebuie verificat înainte să legăm starea de el. Altfel, ne legăm de ID-ul procesului, ca playbook.
- ~~Forma exactă a `agent_type`~~ Confirmat în documentație: `cplugin:worker`, `cplugin:tester`.
- **`CLAUDE_PLUGIN_ROOT` nu există în comenzile Bash ale modelului.** E înlocuit doar în textul skill-urilor și în hook-uri. De aceea proiectul primește launchere în `.claude/bin/`, rescrise la fiecare pornire de sesiune (calea se schimbă la upgrade).
- **Agenții din plugin ignoră `hooks` și `permissionMode` din frontmatter.** Toată impunerea trece prin `hooks/hooks.json`, ceea ce e oricum planul.
- **Un plugin nu poate livra `permissions.deny` sau status line prin setările lui.** De aceea `init` scrie în `.claude/settings.json` al proiectului.
- **Bash nu poate fi oprit înainte**, doar detectat după (4.2).
- **Coexistența cu playbook**: playbook se activează când găsește `.agent/tasks/`. Noi folosim `.cplugin/`, deci nu se activează. `init` îl dezactivează oricum în proiect (`enabledPlugins`), ca Claude să nu-i folosească din greșeală skill-urile.
- **Nu interzicem tool-ul `Agent`** (playbook interzicea `Task`, fostul lui nume). Ar opri sub-agenții.

## 12. Față de playbook

| Păstrăm | Schimbăm | Renunțăm |
|---|---|---|
| task.md ca plan + jurnal, bifat pe rând | Memoria pe două niveluri (MIND_MAP + `mindmap/`) | Jurnalul de mesaje (UserPromptSubmit). Cerința se copiază în task.md |
| Judges care nu văd conversația, verificarea TAMPER | Roluri stricte impuse prin hook (MAIN / worker / tester) | Launcherele Codex/Grok/Pi pentru *scris* cod. Alți furnizori doar ca judges |
| Hook-urile SessionStart, PreToolUse, PostToolUse, Stop, SessionEnd | Hook-uri în Python, cu un singur punct de intrare | Monitorul (al doilea agent care urmărește) |
| Freehand, sandbox | Configurarea agenților într-un singur `config.toml` | Skill-ul de merge multi-user, per-user lanes |
| Curățarea sesiunilor după procesul viu | Tabloul ASCII live; sandbox-ul refuză să pornească neizolat | |

## 13. Decizii deschise

1. **Numele final** al plugin-ului. Deocamdată rămâne `cplugin`.
2. ~~Limba~~ **Decis (2026-10-21): engleză** pentru șabloane, prompturile de rol, mesajele hook-urilor și CLI. SPEC.md rămâne în română.
3. **Câți worker în paralel** implicit. Deocamdată 1, configurabil.
4. **Git obligatoriu?** Deocamdată da: `init` avertizează dacă proiectul nu e repo git. Fără git nu merg verificarea Bash, diff-ul pentru impl-review și TAMPER.

## 14. Ordinea de implementare

Fiecare etapă vine cu teste și se poate folosi independent.

1. ✅ **Schelet** (2026-10-21). Manifest, marketplace local, `init`, șabloane, SessionStart care încarcă `MIND_MAP.md`, `/cplugin:mindmap`. 28 de teste; verificat și cu `claude -p --plugin-dir`.
2. ✅ **Task-uri** (2026-10-21). CLI-ul `tasks` (new/work/stop/done/status/list/pause) + PreToolUse (fără task, creare manuală, 3+ bife, bifă fără rezultat) + PostToolUse (etapa curentă + întrebări) + Stop + SessionEnd. Teste întâi (Roșu/Verde) în șablon. 86 de teste; verificat cu `claude -p`: un task complet parcurs cap-coadă, blocarea editării fără task și blocarea opririi cu etape deschise. `plan-review` și `impl-review` doar afișează un mesaj până la etapa 5.
3. **Agenți și roluri.** `agents/worker.md`, `tester.md`, regulile de roluri în PreToolUse, verificarea Bash, SubagentStart/Stop, `config.toml` + `tasks config check`.
4. **Tablou.** `board.json` + `board --watch` + `/cplugin:board`.
5. **Judges.** Adaptoare Codex și agy, sandbox read-only, TAMPER, panel, rezerva Claude.
6. **Freehand și sandbox.**
