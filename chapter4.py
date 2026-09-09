"""Results Document reports built only from the last verified engine JSON."""
from __future__ import annotations

from pathlib import Path
from typing import Any


TITLE = "Results Document — Statistical Analysis"


def to_markdown(engine: dict[str, Any]) -> str:
    _require_engine(engine)
    results = _results(engine)
    lines = [f"# {TITLE}", "", "## 1 Study and design", "", *_preamble(engine, results), ""]

    raw_tables = _raw_tables(engine)
    if raw_tables:
        lines.extend(["## 2 Raw data table", ""])
        for title, headers, rows in raw_tables:
            if title:
                lines.extend([f"### {title}", ""])
            lines.extend(_markdown_table(headers, rows))
            lines.append("")
    else:
        lines.extend(["## 2 Raw data table", "", "Raw data were not included in the last engine JSON.", ""])

    lines.extend(["## 3 Descriptive tables", ""])
    for index, result in enumerate(results, start=1):
        if len(results) > 1:
            lines.extend([f"### {_outcome_name(result)}", ""])
        lines.extend(_markdown_table(["Treatment", "n", "Mean", "SD"], _descriptive_rows(result)))
        if index < len(results):
            lines.append("")
    lines.extend(["", "## 4 Inferential table", ""])
    lines.extend(_markdown_table(
        ["Outcome", "Test", "Statistic", "df", "p", "Decision"],
        _inferential_rows(results),
    ))
    lines.extend(["", "## 5 Working", ""])
    for result in results:
        lines.extend(f"- {note}" for note in _working_notes(result))
    lines.extend(["", "## 6 Interpretation", ""])
    lines.extend(_interpretations(engine))
    return "\n".join(lines).rstrip() + "\n"


def write_markdown(engine: dict[str, Any], path: str | Path) -> str:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(to_markdown(engine), encoding="utf-8")
    return str(destination)


def write_docx(engine: dict[str, Any], path: str | Path) -> str:
    from docx import Document

    _require_engine(engine)
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    results = _results(engine)
    document = Document()
    document.add_heading("Results Document", level=1)
    document.add_paragraph("Statistical analysis built from the verified engine JSON.")
    document.add_heading("1 Study and design", level=2)
    for paragraph in _preamble(engine, results):
        document.add_paragraph(paragraph)

    document.add_heading("2 Raw data table", level=2)
    raw_tables = _raw_tables(engine)
    if raw_tables:
        for title, headers, rows in raw_tables:
            if title:
                document.add_heading(title, level=3)
            _add_docx_table(document, headers, rows)
    else:
        document.add_paragraph("Raw data were not included in the last engine JSON.")

    document.add_heading("3 Descriptive tables", level=2)
    for index, result in enumerate(results):
        if len(results) > 1:
            document.add_heading(_outcome_name(result), level=3)
        _add_docx_table(document, ["Treatment", "n", "Mean", "SD"], _descriptive_rows(result))
        _embed_chart(document, engine, index)

    document.add_heading("4 Inferential table", level=2)
    _add_docx_table(
        document,
        ["Outcome", "Test", "Statistic", "df", "p", "Decision"],
        _inferential_rows(results),
    )

    document.add_heading("5 Working", level=2)
    for result in results:
        for note in _working_notes(result):
            document.add_paragraph(note, style="List Bullet")

    document.add_heading("6 Interpretation", level=2)
    for paragraph in _interpretations(engine):
        document.add_paragraph(paragraph)
    document.save(destination)
    return str(destination)


def write_pdf(engine: dict[str, Any], path: str | Path) -> str:
    """Render the same engine-JSON report as a PDF."""
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer

    _require_engine(engine)
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    results = _results(engine)
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="RowfirstBody", parent=styles["BodyText"], alignment=TA_LEFT, leading=14))
    styles.add(ParagraphStyle(name="RowfirstSmall", parent=styles["BodyText"], alignment=TA_LEFT, fontSize=8, leading=10))
    story = [
        Paragraph(_escape(TITLE), styles["Title"]),
        PageBreak(),
        Paragraph("1 Study and design", styles["Heading2"]),
    ]
    story.extend(Paragraph(_escape(paragraph), styles["RowfirstBody"]) for paragraph in _preamble(engine, results))
    story.extend([Spacer(1, 0.12 * inch), Paragraph("2 Raw data table", styles["Heading2"])])
    raw_tables = _raw_tables(engine)
    if raw_tables:
        for title, headers, rows in raw_tables:
            if title:
                story.append(Paragraph(_escape(title), styles["Heading4"]))
            story.append(_pdf_table(headers, rows, styles))
            story.append(Spacer(1, 0.1 * inch))
    else:
        story.append(Paragraph("Raw data were not included in the last engine JSON.", styles["RowfirstBody"]))

    story.append(Paragraph("3 Descriptive tables", styles["Heading2"]))
    for result in results:
        if len(results) > 1:
            story.append(Paragraph(_escape(_outcome_name(result)), styles["Heading3"]))
        story.append(_pdf_table(["Treatment", "n", "Mean", "SD"], _descriptive_rows(result), styles))
    story.append(Spacer(1, 0.1 * inch))
    story.append(Paragraph("4 Inferential table", styles["Heading2"]))
    story.append(_pdf_table(
        ["Outcome", "Test", "Statistic", "df", "p", "Decision"],
        _inferential_rows(results),
        styles,
    ))

    story.extend([Spacer(1, 0.18 * inch), Paragraph("5 Working", styles["Heading2"])])
    for result in results:
        for note in _working_notes(result):
            story.append(Paragraph(_escape(note), styles["RowfirstBody"]))
    story.extend([Spacer(1, 0.18 * inch), Paragraph("6 Interpretation", styles["Heading2"])])
    story.extend(Paragraph(_escape(paragraph), styles["RowfirstBody"]) for paragraph in _interpretations(engine))

    SimpleDocTemplate(
        str(destination),
        pagesize=letter,
        rightMargin=0.55 * inch,
        leftMargin=0.55 * inch,
        topMargin=0.55 * inch,
        bottomMargin=0.55 * inch,
    ).build(story)
    return str(destination)


def _preamble(engine: dict[str, Any], results: list[dict[str, Any]]) -> list[str]:
    subject = _subject(engine, results)
    lines = []
    topic = engine.get("topic")
    if topic:
        lines.append(f"Topic: {topic}.")
    lines.extend([
        f"This Results Document presents the statistical analysis of {subject}.",
        f"The analysis used a {_design(results)} design.",
        f"The reported sample sizes were {_sample_description(results)}.",
        "All decisions were made at α = .05.",
    ])
    lines.extend(_hypotheses(engine, results))
    return lines


def _hypotheses(engine: dict[str, Any], results: list[dict[str, Any]]) -> list[str]:
    outcome = _outcome_name(results[0]) if results else "the outcome"
    hypothesis = str(engine.get("ho") or "").strip()
    if hypothesis:
        hypothesis = hypothesis.removeprefix("H0:").removeprefix("Ho:").strip()
        return [
            f"Ho: {hypothesis}",
            f"H1: a difference exists between groups on {outcome}.",
        ]
    return [
        f"Ho: no difference between groups on {outcome}.",
        f"H1: a difference exists between groups on {outcome}.",
    ]


def _subject(engine: dict[str, Any], results: list[dict[str, Any]]) -> str:
    topic = engine.get("topic")
    if topic:
        return str(topic)
    names = []
    for result in results:
        if result.get("parameter"):
            names.append(str(result["parameter"]))
        elif result.get("test") == "two-way anova":
            names.append(str(result.get("outcome", "the measured outcome")))
        elif result.get("test") == "simple linear regression":
            names.append(f"{result.get('predictor', 'predictor')} and {result.get('outcome', 'outcome')}")
        elif result.get("test") in {"pearson", "spearman"}:
            names.append(f"{result.get('xName', 'X')} and {result.get('yName', 'Y')}")
        elif result.get("test") in {"student-t", "welch-t", "one-way anova"}:
            names.append("the treatment groups")
        elif result.get("test") == "paired-t":
            names.append(f"{result.get('before', {}).get('name', 'before')} and {result.get('after', {}).get('name', 'after')}")
        else:
            names.append("the contingency table")
    return ", ".join(dict.fromkeys(names)) or "the submitted data"


def _design(results: list[dict[str, Any]]) -> str:
    labels = []
    for result in results:
        label = {
            "student-t": "independent-samples comparison",
            "welch-t": "independent-samples comparison",
            "paired-t": "paired comparison",
            "one-way anova": "one-way ANOVA",
            "two-way anova": "two-way ANOVA",
            "simple linear regression": "simple linear regression",
            "pearson": "correlation",
            "spearman": "correlation",
            "fisher-exact": "contingency-table analysis",
            "chi-square": "contingency-table analysis",
        }.get(result.get("test"), str(result.get("test") or "the selected statistical test"))
        labels.append(label)
    return ", ".join(dict.fromkeys(labels)) or "the selected statistical test"


def _sample_description(results: list[dict[str, Any]]) -> str:
    parts = []
    for result in results:
        test = result.get("test")
        if test in {"student-t", "welch-t"}:
            parts.append(
                f"{result['group1']['name']} n={result['group1']['n']} and "
                f"{result['group2']['name']} n={result['group2']['n']}"
            )
        elif test == "one-way anova":
            parts.append(", ".join(f"{group['name']} n={group['n']}" for group in result.get("groups", [])))
        elif test == "paired-t":
            parts.append(f"{result['nPairs']} matched pairs")
        elif "n" in result:
            parts.append(f"n={result['n']}")
    return "; ".join(parts) or "not reported by the engine"


def _raw_tables(engine: dict[str, Any]) -> list[tuple[str, list[str], list[tuple[str, ...]]]]:
    ingested = engine.get("ingested") or {}
    fmt = ingested.get("format")
    if fmt in {"long-multi", "factor-multi", "wide-multi"}:
        tables = []
        for outcome in ingested.get("outcomes", []):
            parameter = str(outcome.get("parameter") or "Value")
            rows = [
                (str(group["name"]), _raw_value(value))
                for group in outcome.get("groups", [])
                for value in group.get("values", [])
            ]
            tables.append((parameter, ["Treatment", parameter], rows))
        return tables
    if fmt == "labelled":
        rows = [
            (str(group["name"]), _raw_value(value))
            for group in ingested.get("groups", [])
            for value in group.get("values", [])
        ]
        return [("", ["Treatment", "Value"], rows)]
    if fmt == "paired":
        headers = [str(ingested.get("id", "ID")), str(ingested.get("before", "Before")), str(ingested.get("after", "After"))]
        rows = [
            (str(pair["id"]), _raw_value(pair["before"]), _raw_value(pair["after"]))
            for pair in ingested.get("pairs", [])
        ]
        return [("", headers, rows)]
    if fmt == "two-way":
        headers = [str(ingested.get("factorA", "Factor A")), str(ingested.get("factorB", "Factor B")), str(ingested.get("outcome", "Outcome"))]
        rows = [
            tuple(_raw_value(row.get(header, "")) for header in headers)
            for row in ingested.get("rows", [])
        ]
        return [("", headers, rows)]
    if fmt == "wide":
        groups = ingested.get("groups", [])
        width = max((len(group.get("values", [])) for group in groups), default=0)
        rows = []
        for index in range(width):
            rows.append(tuple([str(index + 1)] + [
                _raw_value(group["values"][index]) if index < len(group.get("values", [])) else ""
                for group in groups
            ]))
        return [("", ["Observation"] + [str(group["name"]) for group in groups], rows)]
    if fmt == "contingency":
        matrix = ingested.get("matrix", [])
        width = max((len(row) for row in matrix), default=0)
        rows = [
            tuple([str(index + 1)] + [_raw_value(value) for value in row] + [""] * (width - len(row)))
            for index, row in enumerate(matrix)
        ]
        return [("", ["Row"] + [f"Column {index + 1}" for index in range(width)], rows)]
    return []


def _raw_value(value: Any) -> str:
    return "" if value is None else str(value)


def _descriptive_rows(result: dict[str, Any]) -> list[tuple[str, str, str, str]]:
    test = result.get("test")
    if test in {"student-t", "welch-t"}:
        return [_group_row(result["group1"]), _group_row(result["group2"])]
    if test == "one-way anova":
        return [_group_row(group) for group in result.get("groups", [])]
    if test == "paired-t":
        return [_group_row(result["before"]), _group_row(result["after"])]
    if test == "two-way anova":
        return [("Factor combinations", str(result.get("n", "not reported")), "not reported", "not reported")]
    if test in {"simple linear regression", "pearson", "spearman"}:
        label = f"{result.get('predictor', result.get('xName', 'X'))} / {result.get('outcome', result.get('yName', 'Y'))}"
        return [(label, str(result.get("n", "not reported")), "not reported", "not reported")]
    return [("Count table", "not reported", "not applicable", "not applicable")]


def _group_row(group: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(group.get("name", "Group")),
        str(group.get("n", "not reported")),
        _fmt_num(group.get("mean")),
        _fmt_num(group.get("sd")),
    )


def _inferential_rows(results: list[dict[str, Any]]) -> list[tuple[str, str, str, str, str, str]]:
    rows = []
    for result in results:
        name = _outcome_name(result)
        test = result.get("test")
        if test in {"student-t", "welch-t", "paired-t"}:
            rows.append((
                name,
                "Paired t-test" if test == "paired-t" else ("Welch t-test" if test == "welch-t" else "Independent t-test"),
                f"t = {result['t']:.12g}",
                _df(result["df"]),
                _fmt_p(result["p"]),
                _decision(result.get("isSignificant", False)),
            ))
        elif test == "one-way anova":
            rows.append((name, "One-way ANOVA", f"F = {result['F']:.12g}", f"{result['dfb']}, {result['dfw']}", _fmt_p(result["p"]), _decision(result.get("isSignificant", False))))
        elif test == "two-way anova":
            for effect in result.get("effects", []):
                rows.append((f"{name} ({effect['effect']})", "Two-way ANOVA", f"F = {effect['F']:.12g}", f"{effect['df']:.0f}, {result['residualDf']:.0f}", _fmt_p(effect["p"]), _decision(effect.get("isSignificant", False))))
        elif test == "simple linear regression":
            rows.append((name, "Simple linear regression", f"r = {result['r']:.12g}", "—", _fmt_p(result["p"]), _decision(result.get("isSignificant", False))))
        elif test in {"pearson", "spearman"}:
            rows.append((name, f"{test.title()} correlation", f"r = {result['r']:.12g}", str(result.get("n", "—")), _fmt_p(result["p"]), _decision(result.get("isSignificant", False))))
        elif test == "fisher-exact":
            rows.append((name, "Fisher exact test", "Exact test", "—", _fmt_p(result["p"]), _decision(result.get("isSignificant", False))))
        else:
            rows.append((name, "Chi-square test", f"χ² = {result['chi2']:.12g}", str(result.get("df", "—")), _fmt_p(result["p"]), _decision(result.get("isSignificant", False))))
    return rows


def _working_notes(result: dict[str, Any]) -> list[str]:
    test = result.get("test")
    if test in {"student-t", "welch-t"}:
        return [
            f"Formula: {'Welch' if test == 'welch-t' else 'independent-samples'} t-test; n={result['group1']['n']} and n={result['group2']['n']}.",
            f"{result['group1']['name']}: mean={result['group1']['mean']:.12g}, SD={result['group1']['sd']:.12g}; {result['group2']['name']}: mean={result['group2']['mean']:.12g}, SD={result['group2']['sd']:.12g}.",
            f"t={result['t']:.12g}, df={_df(result['df'])}, exact p={_fmt_p(result['p'])}.",
        ]
    if test == "paired-t":
        return [
            f"Formula: paired t-test on matched differences; n={result['nPairs']}.",
            f"{result['before']['name']}: mean={result['before']['mean']:.12g}, SD={result['before']['sd']:.12g}; {result['after']['name']}: mean={result['after']['mean']:.12g}, SD={result['after']['sd']:.12g}.",
            f"t={result['t']:.12g}, df={_df(result['df'])}, exact p={_fmt_p(result['p'])}.",
        ]
    if test == "one-way anova":
        group_text = "; ".join(f"{g['name']}: n={g['n']}, mean={g['mean']:.12g}, SD={g['sd']:.12g}" for g in result.get("groups", []))
        return [
            f"Formula: one-way ANOVA; {group_text}.",
            f"F={result['F']:.12g}, df={result['dfb']}, {result['dfw']}, exact p={_fmt_p(result['p'])}.",
        ]
    if test == "two-way anova":
        return [
            f"Formula: two-way ANOVA with {result['factorA']} × {result['factorB']}; n={result['n']}.",
            *[f"{effect['effect']}: F={effect['F']:.12g}, df={effect['df']:.0f}, {result['residualDf']:.0f}, exact p={_fmt_p(effect['p'])}." for effect in result.get("effects", [])],
        ]
    if test == "simple linear regression":
        return [
            f"Formula: simple linear regression; n={result['n']}; predictor={result['predictor']}; outcome={result['outcome']}.",
            f"slope={result['slope']:.12g}, intercept={result['intercept']:.12g}, r={result['r']:.12g}, exact p={_fmt_p(result['p'])}.",
        ]
    if test in {"pearson", "spearman"}:
        return [f"Formula: {test} correlation; n={result['n']}; r={result['r']:.12g}; exact p={_fmt_p(result['p'])}."]
    if test == "fisher-exact":
        return [f"Formula: Fisher exact test for a 2×2 count table; exact p={_fmt_p(result['p'])}."]
    return [f"Formula: chi-square test; χ²={result['chi2']:.12g}, df={result['df']}, exact p={_fmt_p(result['p'])}."]


def _interpretations(engine: dict[str, Any]) -> list[str]:
    breakdown = str(engine.get("breakdown") or "").strip()
    if not breakdown:
        return ["The engine did not provide an interpretation."]
    topic = str(engine.get("topic") or "").strip()
    if topic or engine.get("discuss"):
        subject = topic or "the discussed topic"
        compact = " ".join(line.strip() for line in breakdown.splitlines() if line.strip())
        return [f"Regarding {subject}, {compact}"]
    return ["Overall interpretation: " + " ".join(line.strip() for line in breakdown.splitlines() if line.strip())]


def _outcome_name(result: dict[str, Any]) -> str:
    return str(result.get("parameter") or result.get("outcome") or "Measured outcome")


def _decision(significant: bool) -> str:
    return "Reject H0" if significant else "Fail to reject H0"


def _fmt_num(value: Any) -> str:
    return f"{float(value):.12g}" if isinstance(value, (int, float)) else "not reported"


def _fmt_p(value: Any) -> str:
    return f"{float(value):.12g}" if isinstance(value, (int, float)) else "not reported"


def _df(value: Any) -> str:
    number = float(value)
    return str(int(number)) if abs(number - round(number)) < 1e-6 else f"{number:.12g}"


def _markdown_table(headers: list[str], rows: list[tuple[str, ...]]) -> list[str]:
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    lines.extend("| " + " | ".join(str(value) for value in row) + " |" for row in rows)
    return lines


def _add_docx_table(document: Any, headers: list[str], rows: list[tuple[str, ...]]) -> None:
    table = document.add_table(rows=1, cols=len(headers))
    table.style = "Table Grid"
    for cell, heading in zip(table.rows[0].cells, headers):
        cell.text = str(heading)
    for row in rows:
        cells = table.add_row().cells
        for cell, value in zip(cells, row):
            cell.text = str(value)


def _embed_chart(document: Any, engine: dict[str, Any], result_index: int) -> None:
    """Embed a matching chart when available; a missing PNG never blocks DOCX output."""
    chart = next(
        (
            item for item in (engine.get("charts") or [])
            if item.get("result_index") == result_index
        ),
        None,
    )
    if not chart:
        return
    chart_path = Path(str(chart.get("path", "")))
    if not chart_path.is_file():
        return
    try:
        from docx.shared import Inches

        document.add_paragraph(str(chart.get("caption") or "Chart"))
        document.add_picture(str(chart_path), width=Inches(6.2))
    except Exception:
        return


def _pdf_table(headers: list[str], rows: list[tuple[str, ...]], styles: Any) -> Any:
    from reportlab.lib import colors
    from reportlab.platypus import Paragraph, Table, TableStyle

    data = [[Paragraph(_escape(value), styles["RowfirstSmall"]) for value in headers]]
    data.extend([Paragraph(_escape(str(value)), styles["RowfirstSmall"]) for value in row] for row in rows)
    table = Table(data, repeatRows=1, hAlign="LEFT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#dbeafe")),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]))
    return table


def _escape(value: Any) -> str:
    return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _results(engine: dict[str, Any]) -> list[dict[str, Any]]:
    results = engine.get("results") or [engine.get("result")]
    return [result for result in results if result]


def _require_engine(engine: dict[str, Any]) -> None:
    if not engine or not engine.get("ok", True):
        raise ValueError("A successful engine JSON result is required.")
    if not _results(engine):
        raise ValueError("Engine JSON contains no result.")