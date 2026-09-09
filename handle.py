"""Public analysis API: handle_analyze({text}) -> verified JSON and RESULTS text."""
from __future__ import annotations

import json
import re
from typing import Any

from ingest import ingest_text
from qa import quality_check
from stats_engine import (
    analyze_groups,
    chi_or_fisher,
    correlation,
    linear_regression,
    paired_ttest,
    two_way_anova,
)


UNSUPPORTED = (
    "I can analyse supported descriptive statistics, tests, correlations, and one-predictor "
    "linear regression. Forecasting, multiple regression, GLM, logistic regression, mixed models, "
    "and survival analysis are not supported."
)


def handle_analyze(req: dict) -> dict:
    try:
        request = req or {}
        text = request.get("text") or ""
        if _is_unsupported(text):
            return {"ok": False, "unsupported": True, "error": UNSUPPORTED}
        ingested = ingest_text(text)
        engine = analyze_ingested(ingested, mode=_requested_mode(text, request))
        engine["qa"] = quality_check(ingested)
        engine["breakdown"] = build_breakdown(engine)
        if request.get("study") or request.get("topic"):
            engine["study"] = request.get("study") or request.get("topic")
        return engine
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def analyze_ingested(ingested: dict, mode: str | None = None) -> dict:
    """Run the verified engine over already-ingested local data."""
    fmt = ingested.get("format")
    if fmt == "needs-clarification":
        return {
            "ok": False,
            "needsClarification": True,
            "error": ingested.get("question", "Please identify the intended design before analysis."),
            "question": ingested.get("question"),
            "ingested": ingested,
        }
    if fmt == "contingency":
        result = chi_or_fisher(ingested["matrix"])
        return _success(ingested, [result])
    if fmt == "paired":
        pairs = ingested["pairs"]
        result = paired_ttest(
            [pair["before"] for pair in pairs],
            [pair["after"] for pair in pairs],
            [str(pair["id"]) for pair in pairs],
        )
        result["before"]["name"] = ingested["before"]
        result["after"]["name"] = ingested["after"]
        return _success(ingested, [result])
    if fmt == "two-way":
        result = two_way_anova(ingested["rows"], ingested["factorA"], ingested["factorB"], ingested["outcome"])
        return _success(ingested, [result])

    outcomes = ingested.get("outcomes")
    if outcomes:
        runs = []
        for item in outcomes:
            result = analyze_groups(item["groups"])
            result["parameter"] = item["parameter"]
            runs.append(result)
        return _success(ingested, runs)

    if fmt == "wide" and len(ingested.get("groups", [])) == 2:
        first, second = ingested["groups"]
        if len(first["values"]) != len(second["values"]):
            raise ValueError("The two numeric columns must have the same number of observations.")
        if mode == "correlation":
            result = correlation(first["values"], second["values"])
        else:
            result = linear_regression(first["values"], second["values"], first["name"], second["name"])
        result["xName"] = first["name"]
        result["yName"] = second["name"]
        result["pairs"] = list(zip(first["values"], second["values"]))
        return _success(ingested, [result])
    result = analyze_groups(ingested["groups"])
    return _success(ingested, [result])


def _success(ingested: dict, results: list[dict[str, Any]]) -> dict:
    return {
        "ok": True,
        "ingested": ingested,
        "results": results,
        "result": results[0],
        "message": "\n\n".join(format_result(result) for result in results),
    }


def format_result(r: dict) -> str:
    param = r.get("parameter")
    title = f"{param}\n" if param else ""
    test = r.get("test")
    if test in ("student-t", "welch-t"):
        a, b = r["group1"], r["group2"]
        method = "Welch t-test" if test == "welch-t" else "Independent-samples t-test"
        return (
            f"{title}{method}\n"
            f"{a['name']}: mean={a['mean']:.4f}, SD={a['sd']:.4f}, n={a['n']}\n"
            f"{b['name']}: mean={b['mean']:.4f}, SD={b['sd']:.4f}, n={b['n']}\n"
            f"t({_df(r['df'])}) = {r['t']:.4f}, p = {_p(r['p'])}\n"
            f"Cohen's d = {r['cohensD']:.4f}\n"
            f"{'Significant at α = .05.' if r['isSignificant'] else 'Not significant at α = .05.'}"
        )
    if test == "paired-t":
        return (
            f"{title}Paired t-test\n"
            f"{r['before']['name']}: mean={r['before']['mean']:.4f}, SD={r['before']['sd']:.4f}, n={r['before']['n']}\n"
            f"{r['after']['name']}: mean={r['after']['mean']:.4f}, SD={r['after']['sd']:.4f}, n={r['after']['n']}\n"
            f"mean difference (after − before) = {r['meanDifference']:.4f}\n"
            f"t({_df(r['df'])}) = {r['t']:.4f}, p = {_p(r['p'])}\n"
            f"Cohen's dz = {r['cohensDz']:.4f}\n"
            f"{'Significant at α = .05.' if r['isSignificant'] else 'Not significant at α = .05.'}"
        )
    if test == "one-way anova":
        lines = [f"{title}One-way ANOVA"]
        lines.extend(f"{g['name']}: mean={g['mean']:.4f}, SD={g['sd']:.4f}, n={g['n']}" for g in r["groups"])
        lines.append(f"F({r['dfb']}, {r['dfw']}) = {r['F']:.4f}, p = {_p(r['p'])}")
        lines.append("Significant at α = .05." if r["isSignificant"] else "Not significant at α = .05.")
        return "\n".join(lines)
    if test == "two-way anova":
        lines = [f"{title}Two-way ANOVA ({r['factorA']} × {r['factorB']})"]
        lines.extend(f"{effect['effect']}: F({effect['df']:.0f}, {r['residualDf']:.0f}) = {effect['F']:.4f}, p = {_p(effect['p'])}" for effect in r["effects"])
        if r["interactionSignificant"]:
            lines.append("Interaction is significant; simple effects are needed.")
        return "\n".join(lines)
    if test == "simple linear regression":
        return (
            f"{title}Simple linear regression\n"
            f"{r['outcome']} = {r['intercept']:.4f} + {r['slope']:.4f} × {r['predictor']}\n"
            f"slope={r['slope']:.4f}, intercept={r['intercept']:.4f}, r={r['r']:.4f}, r²={r['rSquared']:.4f}, "
            f"p={_p(r['p'])}, n={r['n']}"
        )
    if test in {"pearson", "spearman"}:
        return (
            f"{title}{test.title()} correlation\n"
            f"r({r['n'] - 2}) = {r['r']:.4f}, p = {_p(r['p'])}, n = {r['n']}\n"
            f"{'Significant at α = .05.' if r['isSignificant'] else 'Not significant at α = .05.'}"
        )
    if test == "fisher-exact":
        return (
            f"{title}Fisher exact test (2x2). Also χ² uncorrected = {r['chi2Uncorrected']:.4f}, "
            f"p_chi = {_p(r['chi2pUncorrected'])}.\n"
            f"Fisher p = {_p(r['p'])}. "
            f"{'Significant at α = .05.' if r['isSignificant'] else 'Not significant at α = .05.'}"
        )
    if test == "chi-square":
        return f"{title}Chi-square: χ²({r['df']}) = {r['chi2']:.4f}, p = {_p(r['p'])}"
    return title + json.dumps(r, default=str)


def build_breakdown(engine: dict[str, Any], max_results: int | None = None) -> str:
    """Build one concise study-level breakdown from verified result fields."""
    results = engine.get("results") or ([engine["result"]] if engine.get("result") else [])
    if max_results is not None:
        results = results[:max_results]
    if not results:
        return "Study overview: no verified outcomes were returned.\n" \
            "Outcomes: none.\n" \
            "Tests: none.\n" \
            "Decisions: none.\n" \
            "Sample sizes: not reported.\n" \
            "Caveat: no interpretation can be made without a successful engine result."

    labels = [_breakdown_label(result) for result in results]
    designs = list(dict.fromkeys(_breakdown_test_name(result) for result in results))
    statistics = [_breakdown_statistic(result) for result in results]
    decisions = [_breakdown_decision(result) for result in results]
    samples = [_breakdown_sample(result) for result in results]
    return "\n".join([
        f"Study overview: {len(results)} outcome(s) were analysed using {', '.join(designs)}.",
        f"Outcomes: {'; '.join(labels)}.",
        f"Tests: {'; '.join(statistics)}.",
        f"Decisions: {'; '.join(decisions)}.",
        f"Sample sizes: {'; '.join(samples)}.",
        "Caveat: these results describe the submitted data and do not establish causation or universal performance.",
    ])


def _breakdown_label(result: dict[str, Any]) -> str:
    return str(result.get("parameter") or result.get("outcome") or "measured outcome")


def _breakdown_test_name(result: dict[str, Any]) -> str:
    return {
        "student-t": "independent t-test",
        "welch-t": "Welch t-test",
        "paired-t": "paired t-test",
        "one-way anova": "one-way ANOVA",
        "two-way anova": "two-way ANOVA",
        "simple linear regression": "simple linear regression",
        "pearson": "Pearson correlation",
        "spearman": "Spearman correlation",
        "fisher-exact": "Fisher exact test",
        "chi-square": "chi-square test",
    }.get(str(result.get("test")), str(result.get("test") or "selected test"))


def _breakdown_statistic(result: dict[str, Any]) -> str:
    test = result.get("test")
    label = _breakdown_label(result)
    if test in {"student-t", "welch-t", "paired-t"}:
        return f"{label}: t({_df(result['df'])}) = {result['t']:.4f}, p = {_p(result['p'])}"
    if test == "one-way anova":
        return f"{label}: F({result['dfb']}, {result['dfw']}) = {result['F']:.4f}, p = {_p(result['p'])}"
    if test == "two-way anova":
        effects = ", ".join(
            f"{effect['effect']} F={effect['F']:.4f}, p={_p(effect['p'])}"
            for effect in result.get("effects", [])
        )
        return f"{label}: {effects or 'effects not reported'}"
    if test == "simple linear regression":
        return f"{label}: r={result['r']:.4f}, r²={result['rSquared']:.4f}, p={_p(result['p'])}"
    if test in {"pearson", "spearman"}:
        return f"{label}: r={result['r']:.4f}, p={_p(result['p'])}"
    if test == "fisher-exact":
        return f"{label}: Fisher p={_p(result['p'])}"
    if test == "chi-square":
        return f"{label}: χ²({result['df']})={result['chi2']:.4f}, p={_p(result['p'])}"
    return f"{label}: statistic not reported"


def _breakdown_decision(result: dict[str, Any]) -> str:
    label = _breakdown_label(result)
    if result.get("test") == "two-way anova":
        significant = [
            str(effect.get("effect"))
            for effect in result.get("effects", [])
            if effect.get("isSignificant")
        ]
        decision = f"significant effect(s): {', '.join(significant)}" if significant else "no significant effects"
    else:
        decision = "significant at α = .05" if result.get("isSignificant") else "not significant at α = .05"
    return f"{label} {decision}"


def _breakdown_sample(result: dict[str, Any]) -> str:
    test = result.get("test")
    label = _breakdown_label(result)
    if test in {"student-t", "welch-t"}:
        return f"{label} n={result['group1']['n']} and n={result['group2']['n']}"
    if test == "one-way anova":
        return f"{label} " + ", ".join(f"{group['name']} n={group['n']}" for group in result.get("groups", []))
    if test == "paired-t":
        return f"{label} {result['nPairs']} matched pairs"
    return f"{label} n={result.get('n', 'not reported')}"


def _breakdown_result(result: dict[str, Any]) -> str:
    test = result.get("test")
    label = result.get("parameter") or result.get("outcome") or "the measured outcome"
    if test in {"student-t", "welch-t"}:
        a, b = result["group1"], result["group2"]
        higher, lower = (a, b) if a["mean"] >= b["mean"] else (b, a)
        trust = "This is unlikely to be only luck." if result["isSignificant"] else "This could still be chance."
        return "\n".join([
            f"What was compared: {a['name']} and {b['name']} for {label}.",
            f"{higher['name']} came out higher ({higher['mean']:.4f}) than {lower['name']} ({lower['mean']:.4f}).",
            f"Test result: t({_df(result['df'])}) = {result['t']:.4f}, p = {_p(result['p'])}.",
            trust,
            f"Difference size (Cohen's d) = {result['cohensD']:.4f}.",
            f"Samples: n={a['n']} and n={b['n']}; this is a signal, not a huge trial.",
            "This does not prove that one method is better or safer for every situation.",
        ])
    if test == "paired-t":
        higher = result["after"]["name"] if result["after"]["mean"] >= result["before"]["mean"] else result["before"]["name"]
        trust = "This is unlikely to be only luck." if result["isSignificant"] else "This could still be chance."
        return "\n".join([
            f"What was compared: matched {result['before']['name']} and {result['after']['name']} values for {label}.",
            f"{higher} had the higher average; the after-minus-before difference was {result['meanDifference']:.4f}.",
            f"Test result: t({_df(result['df'])}) = {result['t']:.4f}, p = {_p(result['p'])}.",
            trust,
            f"Difference size (Cohen's dz) = {result['cohensDz']:.4f}.",
            f"Samples: {result['nPairs']} matched pairs; this is a signal, not a huge trial.",
            "This does not prove that the change will happen for every person or setting.",
        ])
    if test == "one-way anova":
        higher = max(result["groups"], key=lambda group: group["mean"])
        sample_sizes = ", ".join(f"{group['name']} n={group['n']}" for group in result["groups"])
        trust = "This is unlikely to be only luck." if result["isSignificant"] else "This could still be chance."
        return "\n".join([
            f"What was compared: {', '.join(str(group['name']) for group in result['groups'])} for {label}.",
            f"{higher['name']} had the highest average ({higher['mean']:.4f}).",
            f"Test result: F({result['dfb']}, {result['dfw']}) = {result['F']:.4f}, p = {_p(result['p'])}.",
            trust,
            f"Samples: {sample_sizes}; small samples are a signal, not a huge trial.",
            "This result does not prove that every pair of groups is different.",
            "It also does not prove that the highest group is better for every situation.",
        ])
    if test == "two-way anova":
        effects = result["effects"]
        lines = [
            f"What was compared: {result['factorA']}, {result['factorB']}, and their interaction for {result['outcome']}.",
            *[f"{effect['effect']}: F({effect['df']:.0f}, {result['residualDf']:.0f}) = {effect['F']:.4f}, p = {_p(effect['p'])}." for effect in effects],
            "At least one effect is unlikely to be only luck." if result["isSignificant"] else "The tested effects could still be chance.",
            f"Samples: n={result['n']}; this is a signal, not a huge trial.",
            "A significant interaction means simple effects are needed." if result["interactionSignificant"] else "The interaction does not require a simple-effects warning.",
            "This does not prove that one factor combination is best for every situation.",
        ]
        return "\n".join(lines)
    if test == "simple linear regression":
        trust = "This is unlikely to be only luck." if result["isSignificant"] else "This could still be chance."
        return "\n".join([
            f"What was compared: {result['predictor']} as one predictor of {result['outcome']}.",
            f"Higher {result['predictor']} values went with {'higher' if result['slope'] >= 0 else 'lower'} {result['outcome']} values.",
            f"Fitted slope = {result['slope']:.4f}; intercept = {result['intercept']:.4f}.",
            f"Test result: r = {result['r']:.4f}, r² = {result['rSquared']:.4f}, p = {_p(result['p'])}.",
            trust,
            f"Explained share (r²) = {result['rSquared']:.4f}.",
            f"Samples: n={result['n']}; this is a signal, not a huge trial.",
            "This does not prove that the predictor causes the outcome or predicts every case.",
        ])
    if test in {"pearson", "spearman"}:
        trust = "This is unlikely to be only luck." if result["isSignificant"] else "This could still be chance."
        return "\n".join([
            f"What was compared: {result.get('xName', 'X')} and {result.get('yName', 'Y')}.",
            f"The columns moved {'together' if result['r'] >= 0 else 'in opposite directions'} (r = {result['r']:.4f}).",
            f"Test result: p = {_p(result['p'])}.",
            trust,
            f"Relationship size: r = {result['r']:.4f}.",
            f"Samples: n={result['n']}; this is a signal, not a huge trial.",
            "This does not prove that either column causes the other.",
        ])
    if test == "fisher-exact":
        return "\n".join([
            "What was compared: the two-by-two count table.",
            "The table compares how often each category occurred.",
            f"Test result: Fisher p = {_p(result['p'])}; uncorrected chi-square p = {_p(result['chi2pUncorrected'])}.",
            "This is unlikely to be only luck." if result["isSignificant"] else "This could still be chance.",
            f"Association size (odds ratio) = {result['oddsRatio']:.4f}.",
            "The table contains counts, not replicate measurements.",
            "This does not prove that one category causes the other.",
        ])
    if test == "chi-square":
        return "\n".join([
            "What was compared: the observed count table against expected counts.",
            "The table compares observed counts with what would be expected by chance.",
            f"Test result: χ²({result['df']}) = {result['chi2']:.4f}, p = {_p(result['p'])}.",
            "This is unlikely to be only luck." if result["isSignificant"] else "This could still be chance.",
            "The table contains counts, not replicate measurements.",
            "This does not prove that one category causes the other.",
        ])
    return "No plain-English breakdown is available for this engine result."


def _p(p: float) -> str:
    return "< .001" if p < 0.001 else f"{p:.4f}"


def _df(df: float) -> str:
    return str(int(df)) if abs(df - round(df)) < 1e-6 else f"{df:.2f}"


def _requested_mode(text: str, request: dict) -> str | None:
    if request.get("mode") in {"correlation", "regression"}:
        return request["mode"]
    lower = text.lower()
    if "correlation" in lower or "pearson" in lower or "spearman" in lower:
        return "correlation"
    return "regression" if "regression" in lower else None


def _is_unsupported(text: str) -> bool:
    lower = text.lower()
    if any(term in lower for term in ("forecast", "forecasting", "mixed model", "survival analysis", "generalized linear", "glm", "logistic regression", "multiple regression")):
        return True
    return bool(re.search(r"\b\d+\s+predictors?\b", lower))


if __name__ == "__main__":
    import sys

    text = sys.stdin.read() if not sys.argv[1:] else " ".join(sys.argv[1:])
    print(json.dumps(handle_analyze({"text": text}), indent=2, default=str))