# Development reflection and contribution statement

> **DRAFT written with the AI assistant from the project record. Edit it into your own words before submitting,**
> especially the parts marked ✏️, which need your own view. Target: 300–500 words (this draft is about 475,
> leaving room for your own sentence).

## Reflection

I used Claude Code, a terminal-based AI coding assistant, as my development partner. It profiled the data, wrote the
loading, analytics and agent code, wrote tests on tiny made-up tables, and explained each function so I could defend
it. I decided what to build and which numbers to trust, and checked results against Power BI and the raw files.

The most significant analytical challenge was making sure revenue was never duplicated or silently changed. Before
joining anything, I wrote a grain statement for each table. Sales turned out to be one product at one store per
month (21 × 60 × 20 = 25,200 rows), and Products had no category column, so the only route to a category was through
Sales. I wrapped every join in a merge check that compares rows and revenue before and after, and all three joins
left $42,174,440 unchanged. I then confirmed that total against Power BI, against a PowerShell sum of the raw file,
and against the Access database itself. The $1,000 test showed that the app really recalculates: predictions were
committed first, then one row rose by exactly $1,000 with no code change.

The hardest technical challenge was the language-model agent. Gemini's default model was retired mid-project (404),
then the replacement was overloaded (503) and timed out (504). I diagnosed each failure from the error text shown under
the answer, and the fixes were a model switch, retries, and a 60-second limit after which the rules-based assistant
answers. The fallback meant users always got a correct answer, but on the day of testing I had to run the five tests
in rules-based mode and document why.

The AI was strong at writing tested code quickly and at catching its own logic errors when tests failed. It struggled
in ways that needed checking. It first matched keywords inside other words ("earn" in "meaning"), so "What is the
weather in Denver?" returned Denver's revenue. Its first number check rejected Gemini's honest "about 70%" for 70.68%.
Each became a documented fix and retest.

Human judgment was needed for the business meaning. That included treating the website's blank survey scores as "not
surveyed" rather than 0, keeping the two Orlando stores separate when Power BI merged them, and refusing to call any
store "most profitable" from revenue alone. It also meant reading the satisfaction correlation (r = 0.235) as weak
association, not causation.

✏️ *Would I trust it for real decisions?* I would trust its revenue figures, because they are validated several ways
and every answer shows its calculation. I would not trust it for decisions like closing a store. It has no costs,
traffic or staffing data, and its language-model answers depend on a free service. Before real use it would need cost
data, access controls, monitoring of the model's tool choices, and a person reviewing any recommendation.
✏️ *(Add a sentence in your own voice about what you learned or what surprised you.)*

## Contribution statement

| Team member | Main responsibilities | Key calculation or design decision I can explain | Approximate commits |
|---|---|---|---|
| ✏️ *your name* (solo, no Power BI Buddy teammate) | Everything: data profiling and grain statements, data loading and joins, dashboard and filters, analytical tools, rules-based and Gemini assistants, validation against Power BI, the $1,000 test, agent tests, and documentation | Why every join is many-to-one and how `check_merge()` proves revenue is not duplicated; why survey data is compared at store-year grain; how the assistant's number check and fallback work | ✏️ *count with* `git log --oneline \| Measure-Object` |
