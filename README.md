# Greek A2 — Grammar Drill Sheets

Modern Greek (Νέα Ελληνικά) grammar for A1→A2, written as **tables you can cover and recite**.
Scope is **A2 only** — anything belonging to B1 has been left out on purpose.

## Read it

| | |
|---|---|
| 📖 **Online (all 20 sheets)** | https://alexeyanischenko.github.io/Greek-A2-Basics/ |
| 📄 **PDF (62 pages, A4)** | https://alexeyanischenko.github.io/Greek-A2-Basics/greek-a2.pdf |
| ⌨ **Greek keyboard** | https://alexeyanischenko.github.io/Greek-A2-Basics/keyboard.html |

The online version has a light/dark theme switch and a contents sidebar. The PDF is always light,
one sheet per page break, with repeating table headers.

## Contents

| Page | Topic |
|---|---|
| 1 | Index, and **the four cases explained in full** |
| 2 | Alphabet & sounds |
| 3 | Articles |
| 4 | Nouns — all A2 declensions |
| 5 | Plurals |
| 6 | Adjectives |
| 7 | Comparison & adverbs |
| 8 | Pronouns |
| 9 | Verbs — present |
| 10 | Verbs — past (aorist & imperfect) |
| 11 | Verbs — future & subjunctive (θα / να / ας) |
| 12 | Verbs — perfect |
| 13 | Imperative |
| 14 | Adjectives from verbs (-μένος) |
| 15 | Irregular verbs |
| 16 | Prepositions |
| 17 | Conjunctions |
| 18 | Numbers, time & dates |
| 19 | Word order & negation |
| 20 | A2 self-test checklist |
| 21 | The verb είμαι (to be) |

Individual sheets are in [`pages/`](pages/).

## Colour coding

Gender-marked rows and columns are banded: **masculine = blue**, **feminine = purple**,
**neuter = green**.

## Building it yourself

The HTML and PDF are generated from the markdown in this repo:

```
python build.py
```

| Source | |
|---|---|
| `index.md` | the page-1 sheet (contents + the four cases) |
| `grammar/*.md` | the 19 topic sheets |
| `build.py` | markdown → `index.html`, `pages/*.html`, `greek-a2.pdf` |

Output is written in place at the repo root so GitHub Pages serves it straight from `main`.
Only Python (stdlib) is needed; Chrome or Edge is used for the PDF step and is skipped if absent.
`keyboard.html` is hand-written and not generated.
