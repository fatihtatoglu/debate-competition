import argparse
import html
import json
import os
import re
from pathlib import Path


CRITERIA = [
    ("conceptual_clarity", "Conceptual clarity"),
    ("logical_consistency", "Logical consistency"),
    ("strength_of_arguments", "Strength of arguments"),
    ("quality_of_counter_arguments", "Quality of counter-arguments"),
    ("practical_realism", "Practical realism"),
    ("synthesis_and_inference_skills", "Synthesis and inference skills"),
]



def load_records(path: Path) -> list:
    records = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            records.append(json.loads(line))
    return records


def escape(text: str) -> str:
    return html.escape(text or "")


def format_json_block(data) -> str:
    if data is None:
        return ""
    return escape(json.dumps(data, ensure_ascii=False, indent=2))


def render_reasoning_block(reasoning: str) -> str:
    if not reasoning:
        return ""
    return f"""
      <div class="reasoning">
        <div class="panel-title">Reasoning</div>
        <div class="panel-content">{escape(reasoning)}</div>
      </div>
    """


def group_rounds(rounds: list) -> list:
    grouped = {}
    for item in rounds:
        round_id = item.get("id")
        side = item.get("side")
        grouped.setdefault(round_id, {})[side] = item
    return [grouped[key] for key in sorted(grouped.keys())]


def render_round_block(round_id: int, round_data: dict) -> str:
    a = round_data.get("A", {})
    b = round_data.get("B", {})
    prompt_a = a.get("prompt", "")
    prompt_b = b.get("prompt", "")
    round_titles = {
        1: ("Opening", "Initial arguments without rebuttal."),
        2: ("Rebuttal", "Direct response to the opposing opening."),
        3: ("Assumptions", "Analyze framing and hidden assumptions."),
        4: ("Closing", "Synthesis and final position."),
    }
    title, desc = round_titles.get(
        round_id, (f"Round {round_id}", "Response for this round.")
    )
    return f"""
    <div class="round">
      <div class="round-header">
        Round {round_id} - {escape(title)}
        <div class="round-desc">{escape(desc)}</div>
      </div>
      <div class="prompt-row">
        <details class="panel prompt">
          <summary class="panel-title">
            <span class="toggle-icon"></span>
            Prompt A
          </summary>
          <pre>{escape(prompt_a)}</pre>
        </details>
      </div>
      <div class="response-row response-a">
        <div class="panel side-a">
          <div class="panel-title">Model A</div>
          <pre class="model-output">{escape(a.get("content", ""))}</pre>
          {render_reasoning_block(a.get("reasoning", ""))}
        </div>
      </div>
      <div class="prompt-row">
        <details class="panel prompt">
          <summary class="panel-title">
            <span class="toggle-icon"></span>
            Prompt B
          </summary>
          <pre>{escape(prompt_b)}</pre>
        </details>
      </div>
      <div class="response-row response-b">
        <div class="panel side-b">
          <div class="panel-title">Model B</div>
          <pre class="model-output">{escape(b.get("content", ""))}</pre>
          {render_reasoning_block(b.get("reasoning", ""))}
        </div>
      </div>
    </div>
    """


def render_record(record: dict, index: int) -> str:
    rounds = group_rounds(record.get("rounds", []))
    rounds_html = "\n".join(
        render_round_block(idx + 1, r) for idx, r in enumerate(rounds)
    )

    evaluation = record.get("evaluation", {})
    jury_results = evaluation.get("juries", [])
    jury_parsed_list = evaluation.get("parsed", [])
    if isinstance(jury_parsed_list, dict):
        jury_parsed_list = [jury_parsed_list]

    result = record.get("result", {})
    general = result.get("general", "")
    winner = result.get("winner", "")
    winning_reason = result.get("winning_reason", "")

    total_duration = record.get("total_duration_seconds")
    duration_line = ""
    if isinstance(total_duration, (int, float)):
        duration_line = f"<div><strong>Total Duration:</strong> {total_duration:.2f}s</div>"

    totals = {
        "A": {"cost": 0.0, "tokens": 0},
        "B": {"cost": 0.0, "tokens": 0},
    }
    for item in record.get("rounds", []):
        side = item.get("side")
        if side in totals:
            totals[side]["cost"] += float(item.get("cost") or 0.0)
            totals[side]["tokens"] += int(item.get("total_tokens") or 0)

    jury_cost = sum(float(item.get("cost") or 0.0) for item in jury_results)
    jury_tokens = sum(int(item.get("total_tokens") or 0) for item in jury_results)

    model_a = record.get("proposition", "")
    model_b = record.get("opposition", "")
    jury_model = record.get("jury", "")

    jury_parsed = jury_parsed_list[0] if jury_parsed_list else {}
    reasoning = jury_parsed.get("reasoning", "")

    total_score_a = 0.0
    total_score_b = 0.0
    scored_count = 0
    for parsed in jury_parsed_list:
        try:
            total_score_a += float(parsed.get("total_score_A") or 0.0)
            total_score_b += float(parsed.get("total_score_B") or 0.0)
            scored_count += 1
        except (TypeError, ValueError):
            continue
    avg_score_a = total_score_a / scored_count if scored_count else 0.0
    avg_score_b = total_score_b / scored_count if scored_count else 0.0

    def ensure_dict(value) -> dict:
        return value if isinstance(value, dict) else {}

    def build_score_table(details_a: dict, details_b: dict, total_a, total_b) -> str:
        details_a = ensure_dict(details_a)
        details_b = ensure_dict(details_b)
        score_keys = []
        for key in details_a.keys():
            if key not in score_keys:
                score_keys.append(key)
        for key in details_b.keys():
            if key not in score_keys:
                score_keys.append(key)
        header_cells = "".join(
            f"<th>{escape(key.replace('_', ' ').title())}</th>" for key in score_keys
        )
        a_cells = "".join(
            f"<td>{escape(str(details_a.get(key, '')))}</td>" for key in score_keys
        )
        b_cells = "".join(
            f"<td>{escape(str(details_b.get(key, '')))}</td>" for key in score_keys
        )
        return f"""
        <table class="scores">
          <thead>
            <tr>
              <th>Side</th>
              {header_cells}
              <th>Total</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>Side A ({escape(model_a)})</td>
              {a_cells}
              <td>{escape(str(total_a))}</td>
            </tr>
            <tr>
              <td>Side B ({escape(model_b)})</td>
              {b_cells}
              <td>{escape(str(total_b))}</td>
            </tr>
          </tbody>
        </table>
        """

    per_jury_sections = []
    for idx, parsed in enumerate(jury_parsed_list, start=1):
        details_a = parsed.get("detailed_scores_A") or {}
        details_b = parsed.get("detailed_scores_B") or {}
        total_a = parsed.get("total_score_A", "")
        total_b = parsed.get("total_score_B", "")
        judge_summary = parsed.get("general", "")
        judge_reasoning = parsed.get("reasoning", "")
        model_name = ""
        if idx - 1 < len(jury_results):
            model_name = jury_results[idx - 1].get("model", "")
        summary_block = (
            f'<div class="jury-reasoning">{escape(judge_summary)}</div>'
            if judge_summary
            else ""
        )
        reason_block = (
            f'<div class="jury-winning-reason"><strong>Winning Reason:</strong> {escape(judge_reasoning)}</div>'
            if judge_reasoning
            else ""
        )
        per_jury_sections.append(
            f"""
            <div class="panel-title">Jury {idx} ({escape(model_name)})</div>
            {summary_block}
            {build_score_table(details_a, details_b, total_a, total_b)}
            {reason_block}
            """
        )
    per_jury_tables_html = "".join(per_jury_sections)

    debate_id = record.get("id", f"debate-{index}")
    jury_totals_rows = []
    for idx, item in enumerate(jury_results, start=1):
        item_tokens = int(item.get("total_tokens") or 0)
        item_cost = float(item.get("cost") or 0.0)
        jury_totals_rows.append(
            "<tr>"
            f"<td>Jury {idx} ({escape(str(item.get('model', '')) )})</td>"
            f"<td>{item_tokens}</td>"
            f"<td>{item_cost:.6f}</td>"
            "</tr>"
        )
    jury_totals_html = "".join(jury_totals_rows)
    total_tokens_all = totals["A"]["tokens"] + totals["B"]["tokens"] + jury_tokens
    total_cost_all = totals["A"]["cost"] + totals["B"]["cost"] + jury_cost

    return f"""
  <section class="debate" id="debate-{escape(str(debate_id))}">
    <div class="meta">
      <div><strong>Topic:</strong> {escape(record.get("topic", ""))}</div>
      <div><strong>Conditions:</strong> {escape(record.get("conditions", ""))}</div>
      <div><strong>Model A:</strong> {escape(model_a)}</div>
      <div><strong>Model B:</strong> {escape(model_b)}</div>
      <div><strong>Jury:</strong> {escape(jury_model)}</div>
      {duration_line}
    </div>

    <div class="general">
      <div class="panel-title">General Summary</div>
      <div class="panel-content">{escape(general)}</div>
    </div>

    <div class="totals-card">
      <div class="panel-title">Totals</div>
      <table class="totals">
        <thead>
          <tr>
            <th>Model</th>
            <th>Total Tokens</th>
            <th>Total Cost (USD)</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>{escape(model_a)}</td>
            <td>{totals["A"]["tokens"]}</td>
            <td>{totals["A"]["cost"]:.6f}</td>
          </tr>
          <tr>
            <td>{escape(model_b)}</td>
            <td>{totals["B"]["tokens"]}</td>
            <td>{totals["B"]["cost"]:.6f}</td>
          </tr>
          {jury_totals_html}
          <tr>
            <td><strong>Total</strong></td>
            <td><strong>{total_tokens_all}</strong></td>
            <td><strong>{total_cost_all:.6f}</strong></td>
          </tr>
        </tbody>
      </table>
    </div>

    {rounds_html}

    <div class="jury">
      <div class="panel-title">Jury Result</div>
      <div class="panel-content">
        {per_jury_tables_html}
        <div class="panel-title">Jury Totals</div>
        <table class="scores">
          <thead>
            <tr>
              <th></th>
              <th>Total Score A</th>
              <th>Total Score B</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>Sum</td>
              <td>{total_score_a:.2f}</td>
              <td>{total_score_b:.2f}</td>
            </tr>
            <tr>
              <td>Average</td>
              <td>{avg_score_a:.2f}</td>
              <td>{avg_score_b:.2f}</td>
            </tr>
          </tbody>
        </table>
        <div class="winner">Winner: {escape(winner)}</div>
      </div>
    </div>
  </section>
  """


def render_human_record(record: dict, index: int) -> str:
    rounds = group_rounds(record.get("rounds", []))
    round_titles = {
        1: ("Opening", "Initial arguments without rebuttal."),
        2: ("Rebuttal", "Direct response to the opposing opening."),
        3: ("Assumptions", "Analyze framing and hidden assumptions."),
        4: ("Closing", "Synthesis and final position."),
    }
    rounds_html = "\n".join(
        f"""
        <div class="round">
          <div class="round-header">
            Round {idx + 1} - {escape(round_titles.get(idx + 1, ('Round', ''))[0])}
            <div class="round-desc">{escape(round_titles.get(idx + 1, ('', ''))[1])}</div>
          </div>
          <div class="response-row response-a">
            <div class="panel side-a">
              <div class="panel-title">Side A</div>
              <pre class="model-output">{escape(r.get("A", {}).get("content", ""))}</pre>
            </div>
          </div>
          <div class="response-row response-b">
            <div class="panel side-b">
              <div class="panel-title">Side B</div>
              <pre class="model-output">{escape(r.get("B", {}).get("content", ""))}</pre>
            </div>
          </div>
        </div>
        """
        for idx, r in enumerate(rounds)
    )

    debate_id = record.get("id", f"debate-{index}")
    conditions = record.get("conditions", "")

    criteria_rows = "\n".join(
        f"""
        <tr>
          <td>{escape(label)}</td>
          <td><input type="number" name="a_{key}" min="0" max="20" required></td>
          <td><input type="number" name="b_{key}" min="0" max="20" required></td>
        </tr>
        """
        for key, label in CRITERIA
    )


    return f"""
  <section class="debate" id="debate-{escape(str(debate_id))}">
    <div class="meta">
      <div><strong>Topic:</strong> {escape(record.get("topic", ""))}</div>
      <div><strong>Conditions:</strong> {escape(conditions)}</div>
      <div><strong>Participants:</strong> Side A vs Side B</div>
    </div>

    {rounds_html}

    <form class="human-form" data-debate-id="{escape(str(debate_id))}" data-topic="{escape(record.get("topic", ""))}" data-conditions="{escape(conditions)}">
      <div class="panel-title">Human Evaluation</div>
      <table class="scores">
        <thead>
          <tr>
            <th>Criteria</th>
            <th>Side A (0-20)</th>
            <th>Side B (0-20)</th>
          </tr>
        </thead>
        <tbody>
          {criteria_rows}
        </tbody>
      </table>
      <div class="form-row">
        <label>Winner (auto)</label>
        <input type="text" name="winner_display" readonly>
        <input type="hidden" name="winner">
      </div>
      <div class="form-row">
        <label>Why did Side A or Side B win (or why is it a tie)?</label>
        <textarea name="reasoning" required minlength="20"></textarea>
      </div>
      <div class="form-row">
        <label>Full Name</label>
        <input type="text" name="full_name" required>
      </div>
      <div class="form-row">
        <label>Email</label>
        <input type="email" name="email" required>
      </div>
      <div class="form-actions">
        <button type="submit">Submit</button>
        <span class="form-status" aria-live="polite"></span>
      </div>
    </form>
  </section>
  """


def build_html(records: list, css_href: str) -> str:
    body = "\n".join(render_record(r, i) for i, r in enumerate(records, start=1))
    topic_map = {}
    for i, record in enumerate(records, start=1):
        debate_id = record.get("id", f"debate-{i}")
        topic = record.get("topic", "Untitled")
        topic_map.setdefault(topic, []).append(debate_id)

    nav_groups = []
    for topic, debate_ids in topic_map.items():
        items_html = "\n".join(
            f'<button class="nav-item" data-target="debate-{escape(str(d_id))}">{escape(str(d_id))}</button>'
            for d_id in debate_ids
        )
        nav_groups.append(
            f"""
            <details class="nav-group" open>
              <summary class="nav-group-title">{escape(topic)}</summary>
              <div class="nav-group-items">
                {items_html}
              </div>
            </details>
            """
        )
    nav_html = "\n".join(nav_groups)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Debate Output</title>
  <link rel="stylesheet" href="{css_href}">
</head>
<body>
  <div class="layout">
    <aside class="sidebar">
      <h2>Debates</h2>
      {nav_html}
    </aside>
    <main class="content">
      {body}
      <footer class="signature">
        Fatih Tatoğlu - <a href="https://tatoglu.net" target="_blank" rel="noopener">https://tatoglu.net</a>
      </footer>
    </main>
  </div>
  <script>
    const items = document.querySelectorAll('.nav-item');
    const debates = document.querySelectorAll('.debate');
    function showDebate(id) {{
      debates.forEach((el) => {{
        el.style.display = el.id === id ? 'block' : 'none';
      }});
      items.forEach((btn) => {{
        btn.classList.toggle('active', btn.dataset.target === id);
      }});
    }}
    if (items.length) {{
      showDebate(items[0].dataset.target);
      items.forEach((btn) => {{
        btn.addEventListener('click', () => showDebate(btn.dataset.target));
      }});
    }}
  </script>
</body>
</html>
"""


def build_human_html(records: list, css_href: str) -> str:
    body = "\n".join(
        render_human_record(r, i) for i, r in enumerate(records, start=1)
    )
    topic_map = {}
    for i, record in enumerate(records, start=1):
        debate_id = record.get("id", f"debate-{i}")
        topic = record.get("topic", "Untitled")
        topic_map.setdefault(topic, []).append(debate_id)

    nav_groups = []
    for topic, debate_ids in topic_map.items():
        items_html = "\n".join(
            f'<button class="nav-item" data-target="debate-{escape(str(d_id))}">{escape(str(d_id))}</button>'
            for d_id in debate_ids
        )
        nav_groups.append(
            f"""
            <details class="nav-group" open>
              <summary class="nav-group-title">{escape(topic)}</summary>
              <div class="nav-group-items">
                {items_html}
              </div>
            </details>
            """
        )
    nav_html = "\n".join(nav_groups)

    score_js_lines = []
    for key, _label in CRITERIA:
        score_js_lines.append(
            f"scores.side_a['{key}'] = Number(data.get('a_{key}'));"
        )
        score_js_lines.append(
            f"scores.side_b['{key}'] = Number(data.get('b_{key}'));"
        )
    score_js = "\n        ".join(score_js_lines)

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Debate Output (Human Review)</title>
  <link rel="stylesheet" href="{css_href}">
</head>
<body>
  <div class="layout">
    <aside class="sidebar">
      <h2>Debates</h2>
      {nav_html}
    </aside>
    <main class="content">
      {body}
      <footer class="signature">
        Fatih Tatoğlu - <a href="https://tatoglu.net" target="_blank" rel="noopener">https://tatoglu.net</a>
      </footer>
    </main>
  </div>
  <script>
    const items = document.querySelectorAll('.nav-item');
    const debates = document.querySelectorAll('.debate');
    function showDebate(id) {{
      debates.forEach((el) => {{
        el.style.display = el.id === id ? 'block' : 'none';
      }});
      items.forEach((btn) => {{
        btn.classList.toggle('active', btn.dataset.target === id);
      }});
    }}
    if (items.length) {{
      showDebate(items[0].dataset.target);
      items.forEach((btn) => {{
        btn.addEventListener('click', () => showDebate(btn.dataset.target));
      }});
    }}

    document.querySelectorAll('.human-form').forEach((form) => {{
      form.addEventListener('submit', async (e) => {{
        e.preventDefault();
        const status = form.querySelector('.form-status');
        status.textContent = 'Submitting...';
        const data = new FormData(form);
        const payload = {{
          debate_id: form.dataset.debateId,
          topic: form.dataset.topic,
          conditions: form.dataset.conditions,
          scores: {{
            side_a: {{}},
            side_b: {{}},
          }},
          winner: data.get('winner'),
          reasoning: data.get('reasoning'),
          full_name: data.get('full_name'),
          email: data.get('email'),
        }};
        const scores = payload.scores;
        {score_js}
        try {{
          const res = await fetch('https://example.com/submit', {{
            method: 'POST',
            headers: {{ 'Content-Type': 'application/json' }},
            body: JSON.stringify(payload),
          }});
          if (res.ok) {{
            status.textContent = 'Submitted.';
            form.reset();
          }} else {{
            status.textContent = 'Failed. Please try again.';
          }}
        }} catch (err) {{
          status.textContent = 'Failed. Please try again.';
        }}
      }});
    }});

    function updateWinner(form) {{
      const data = new FormData(form);
      let totalA = 0;
      let totalB = 0;
      const scores = {{ side_a: {{}}, side_b: {{}} }};
      {score_js}
      Object.values(scores.side_a).forEach((v) => totalA += v);
      Object.values(scores.side_b).forEach((v) => totalB += v);
      const winnerField = form.querySelector('input[name="winner"]');
      const winnerDisplay = form.querySelector('input[name="winner_display"]');
      if (totalA > totalB) {{
        winnerField.value = 'Side A';
        winnerDisplay.value = 'Side A';
      }} else if (totalB > totalA) {{
        winnerField.value = 'Side B';
        winnerDisplay.value = 'Side B';
      }} else {{
        winnerField.value = 'Tie';
        winnerDisplay.value = 'Tie';
      }}
    }}

    document.querySelectorAll('.human-form').forEach((form) => {{
      form.addEventListener('input', () => updateWinner(form));
      updateWinner(form);
    }});
  </script>
</body>
</html>
"""


def minify_html(html_text: str) -> str:
    parts = re.split(r"(<pre.*?>.*?</pre>)", html_text, flags=re.DOTALL)
    out = []
    for part in parts:
        if part.startswith("<pre"):
            out.append(part)
            continue
        compact = re.sub(r">\s+<", "><", part)
        compact = re.sub(r"\s{2,}", " ", compact)
        out.append(compact.strip())
    return "".join(out)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path, help="Path to JSONL output.")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("outputs/debate.html"),
        help="Output HTML file path.",
    )
    parser.add_argument(
        "--human-output",
        type=Path,
        default=Path("outputs/human.html"),
        help="Output HTML file path for human review.",
    )
    args = parser.parse_args()

    records = load_records(args.input)
    css_href_main = os.path.relpath(Path("styles.css"), args.output.parent)
    css_href_human = os.path.relpath(Path("styles.css"), args.human_output.parent)
    html_text = build_html(records, css_href_main)
    human_html_text = build_human_html(records, css_href_human)
    args.output.write_text(minify_html(html_text), encoding="utf-8")
    args.human_output.write_text(minify_html(human_html_text), encoding="utf-8")
    print(f"HTML written to {args.output}")
    print(f"Human HTML written to {args.human_output}")


if __name__ == "__main__":
    main()
