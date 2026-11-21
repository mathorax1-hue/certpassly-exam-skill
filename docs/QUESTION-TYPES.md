# Question types read from a PDF

The technical phase (PDF to site v2, no AI by default) builds a question only
when exactly one type fits, every word is accounted for, and the answer comes
from the PDF. Anything else is held with a reason. The upstream code is in
`patches/upstream/v1.3.0-question-type-builders.patch`.

## How each type is found

| Type | What the PDF must show | Answer key from |
|---|---|---|
| single_choice, multiple_select, true_false | lettered options, answer letters | answer line |
| image_based_choice | lettered options and an exhibit image | answer line |
| scenario_standalone | stem starts with `Scenario:`, one answer letter | answer line |
| case_study_group | `Case Study: <title>` text, members with a `Question:` line | answer line |
| yes_no_matrix | answer area with Yes and No columns, one control per row | 2 pixel methods agree |
| single_choice_matrix | grid of radios with a unique text header over each column | 2 pixel methods agree |
| inline_dropdown, multi_blank_dropdown | drop-down lists in the answer area, sentence text around them | 2 pixel methods agree |
| hotspot_single, hotspot_multi | `HOTSPOT` stem, labelled boxes, marked box in the answer image | 2 pixel methods agree |
| ordering | stem says order or arrange, numbered steps, answer is every step once | answer line |
| matching | stem says match, numbered items, lettered targets, pairs like `1-B` | answer line |
| categorization | stem says categorize or classify, pairs item to category | answer line |
| drag_drop | stem says drag, pairs item to slot | answer line |
| multi_select_matrix (staging, draft only) | grid of controls; at least one row has more than one marked column, or the stem says you may select more than one column | 2 pixel methods agree; key is `{row: [columns]}` |
| text_cloze (staging, draft only) | stem says type the missing word or fill in each blank; blanks are ______ or [blank] | answer line, one value per blank |
| short_text (staging, draft only) | stem says type a short answer; no lettered options | answer line accepted list (`{accepted, match}`) |
| numeric (staging, draft only) | stem says enter the number; no lettered options | answer line value or range, optional unit and tolerance |

Lab, simulation, adaptive and the other blocked types stay held. The four staging types above are built and imported as drafts only; they are not publishable until the site flag is on.

## Reading rules

- The answer area is found by layout (controls, list boxes, combo boxes, labelled
  boxes). More than one layout fitting means hold.
- Marks are read by at least two pixel methods of different families. Any
  conflicting method means hold.
- UI labels such as "Answer Area" and control glyphs are removed from the OCR
  words only when the layout was read. Every other word is still checked.
- A sharper OCR set (4x, then 1x plus 2x) is tried only for an answer area or an
  exhibit that is held for reading reasons. Both passes of a set must agree and
  reach the word threshold, and every confident word of the default read must
  still be in the export, so a sharper read cannot hide a line.

## Site shapes

- matrix: `interaction.matrix.rows[{id,text}]`, `columns[{id,text}]`, key `{row: column}` (single) or `{row: [columns]}` (multi_select_matrix).
- cloze dropdowns: `interaction.cloze.segments` and `blanks[{id,options[{id,text}]}]`, key `{blank: option id}`.
- text_cloze: same cloze segments, blanks have `kind: text` and no options, key `{blank: value}`.
- short_text: `{accepted: [..], match: text|expression|number}`.
- numeric: `{value}` or `{range: [min, max]}`, optional `tolerance`, `tolerance_type`, `unit`.
- ordering: `interaction.ordering`, key is item indexes in order; the learner answers item index to 1 based position.
- matching: `interaction.matching_pairs`; the key maps item index to the target index after the site sort (unique, natural, case insensitive).
- categorization and drag_drop: items are `learner.choices`, slots are `interaction.drag_slots`, key `{item: slot}`.
- hotspot: `interaction.hotspot_regions[{id,label,shape:rect,coords}]` with normalized coords.
- scenario and case study: `content_blocks` with a `case_study` block, then a single choice question.

## Regression set

`tests/fixtures/question-types` holds a synthetic TEST ONLY PDF with one
question per type, including the four staging types, plus expected holds. It is never promoted
(`promote_ready_exam.py` refuses `QTYPE-FIXTURE`). Run it with:

    python3 scripts/run_question_type_fixtures.py --upstream <patched upstream> [--sandbox <local import sandbox>]

`scripts/site_import_gate.php --grade-all` grades a correct and a near-miss
wrong response for every question and checks that every key points at an id
the learner sees.
