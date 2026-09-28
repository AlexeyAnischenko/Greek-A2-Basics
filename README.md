# Greek A2 — Grammar Drill Sheets

Modern Greek (Νέα Ελληνικά) grammar for A1→A2, written as **tables you can cover and recite**.
Scope is **A2 only** — anything belonging to B1 has been left out on purpose.

## Read it

| | |
|---|---|
| 📖 **Online (all 22 sheets)** | https://alexeyanischenko.github.io/Greek-A2-Basics/ |
| 📄 **PDF (70 pages, A4)** | https://alexeyanischenko.github.io/Greek-A2-Basics/greek-a2.pdf |
| ⌨ **Greek keyboard** | https://alexeyanischenko.github.io/Greek-A2-Basics/keyboard.html |
| 🖨 **Noun endings, one page to print** | https://alexeyanischenko.github.io/Greek-A2-Basics/master-grid.pdf |
| ▦ **Adjective endings, master grid** | https://alexeyanischenko.github.io/Greek-A2-Basics/adjective-grid.html |
| ▦ **Verb endings, master grid** | https://alexeyanischenko.github.io/Greek-A2-Basics/verb-grid.html |
| ▦ **Nouns and adjectives, one grid** | https://alexeyanischenko.github.io/Greek-A2-Basics/mega-grid.html |

The online version has a light/dark theme switch and a contents sidebar. The PDF is always light,
one sheet per page break, with repeating table headers.

## Contents

| Page | Topic |
|---|---|
| 1 | Contents and how to use these sheets |
| 2 | Alphabet & sounds |
| 3 | Articles |
| 4 | Nouns — all A2 declensions |
| 5 | **The four cases** — what each is for, and the question words |
| 6 | Plurals |
| 7 | Adjectives |
| 8 | Comparison & adverbs |
| 9 | Pronouns |
| 10 | Verbs — present |
| 11 | Verbs — past (aorist & imperfect) |
| 12 | Verbs — future & subjunctive (θα / να / ας) |
| 13 | Verbs — perfect |
| 14 | Imperative |
| 15 | Adjectives from verbs (-μένος) |
| 16 | Irregular verbs |
| 17 | Prepositions |
| 18 | Conjunctions |
| 19 | Numbers, time & dates |
| 20 | Word order & negation |
| 21 | The verb είμαι (to be) |
| 22 | A2 self-test checklist |

Individual sheets are in [`pages/`](pages/).

## Colour coding

Gender-marked rows and columns are banded: **masculine = blue**, **feminine = purple**,
**neuter = green**. The verb grid has no gender to band, so it bands the **tense family**
instead: **present = amber**, **past = rose**, **future and να = cyan**.

## The master grids

Four generated one-table pages, all built the same way: a row-label column on the left, two
grouping levels across the top with a button that swaps them, colour bands down the rows, the
ending in the cell, and a hover balloon on every cell with a sentence that uses that exact form.
The balloon text lives in `grammar/data/examples.tsv`, keyed by row label and column number.

## Building it yourself

The HTML and PDF are generated from the markdown in this repo:

```
python build.py            # HTML + both PDFs
python build.py --no-pdf   # HTML only, skips the Chrome print step
```

| Source | |
|---|---|
| `index.md` | the page-1 sheet (contents + how to drill) |
| `grammar/*.md` | the 21 topic sheets |
| `build.py` | markdown → `index.html`, `pages/*.html`, `greek-a2.pdf` |

Output is written in place at the repo root so GitHub Pages serves it straight from `main`.
Only Python (stdlib) is needed; Chrome or Edge is used for the PDF step and is skipped if absent.
`keyboard.html` is hand-written and not generated.

### Output

| Output | What it is |
|---|---|
| `index.html` | All 22 sheets in one self-contained file, with a sticky contents sidebar |
| `pages/*.html` | One standalone file per sheet |
| `greek-a2.pdf` | 70-page A4 print, one sheet per page break, colour bands preserved |
| `master-grid.html` / `.pdf` | the noun grid alone, one A4 page, grouped by case |
| `adjective-grid.html` | the adjective grid: type × gender down the side, case × number across, banded by gender |
| `verb-grid.html` | the verb grid: tense × group down the side, person × number across, banded by tense family |
| `mega-grid.html` | the noun and adjective grids merged, gender band by gender band |

The build needs only Python (stdlib) plus Chrome or Edge for the PDF step; if neither is
found the HTML is still written and the PDF step is skipped.

In the HTML and PDF the gender bands are real cell backgrounds that fill the whole row.

### Theme switch

Every HTML file (the combined one and each per-sheet file) has a pill button in the top-right
corner that cycles:

| Label | Behaviour |
|---|---|
| **Auto** | follows the OS / browser setting via `prefers-color-scheme` (the default) |
| **Light** | pinned light, ignores the OS setting |
| **Dark** | pinned dark, ignores the OS setting |

The choice is stored in `localStorage` under `greek-a2-theme` and survives reloads. A tiny
script in `<head>` applies it before first paint, so a pinned dark theme does not flash white.
Dark mode uses deeper gender bands with light text rather than the pastel ones.

#### Why `color-scheme` is written the way it is

Do not "simplify" these three declarations:

| Selector | Value | Reason |
|---|---|---|
| `:root` | `light dark` | must advertise dark support **at all times** |
| `:root[data-theme="light"]` | `only light` | explicit opt-out of forced darkening |
| `:root[data-theme="dark"]` | `only dark` | same, for the pinned dark theme |

Chrome's **Auto Dark Mode for Web Contents** (`chrome://flags/#enable-force-dark`) inverts any
page whose root resolves to light-only. With plain `color-scheme: light` the Light setting was
silently inverted back to a black background, so the toggle appeared to do nothing but nudge the
text colour. The `only` keyword is the documented opt-out. Verified by rendering each state with
`--enable-features=WebContentsForceDark` and confirming the output is byte-identical to a normal
render.

⚠ The **PDF is always light**, whatever theme is selected — the print stylesheet resets the
palette. Worth knowing because headless Chrome reports `prefers-color-scheme: dark`, so without
that reset the PDF would have printed dark.
