"""Generate every results figure used by the report, the deck and the paper.

Reads only paper/numbers.json, the experiment log and the demo output, so a
re-run after any new experiment regenerates figures that agree with the text.

    pip install -e ".[docs]"          # inside the project's virtual environment
    python -m paper.collect
    python docs/figures/make_figures.py

The design figures from Review 2 (Gantt, architecture, DFD, use case, class,
sequence) are static and live alongside these as fig1_* to fig6_*.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyBboxPatch  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
N = json.loads((ROOT / "paper/numbers.json").read_text(encoding="utf-8"))

NAVY, ORANGE, GREEN, GREY, LIGHT = "#1F3864", "#C55A11", "#375623", "#7F7F7F", "#D9E2F3"
COND = [("stripped_plain", "Floor\n(intent withheld)", GREY),
        ("stripped_clarify", "Treatment\n(ClarifyReview)", ORANGE),
        ("full_plain", "Ceiling\n(full context)", NAVY)]

plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 10, "axes.spines.top": False,
    "axes.spines.right": False, "axes.titleweight": "bold", "axes.titlesize": 11,
    "savefig.dpi": 220, "savefig.bbox": "tight",
})


def _save(fig, name: str) -> None:
    fig.savefig(OUT / name)
    plt.close(fig)
    print("wrote", OUT / name)


# ------------------------------------------------------------- results

def fig_results(study_key: str = "v2", name: str = "fig7_results.png",
                inset: bool = False) -> None:
    """Three panels (intent, defect, false alarm). n comes from the data, not the title."""
    t = N[study_key]["tests"]
    panels = [
        ("Intent recovered\n(all {n} instances)", t["intent_all"]),
        ("Injected defect caught\n({n} verified mutants)", t["defect_mutant"]),
        ("False alarm raised\n({n} correct patches)", t["false_alarm_golden"]),
    ]
    key = {"stripped_plain": "floor", "stripped_clarify": "treatment", "full_plain": "ceiling"}
    fig, axes = plt.subplots(1, 3, figsize=(10, 3.4))
    for ax, (title, d) in zip(axes, panels):
        n = d["n"]
        vals = [d[key[c]] * 100 for c, _, _ in COND]
        bars = ax.bar(range(3), vals, color=[c for _, _, c in COND], width=0.62)
        for b, v in zip(bars, vals):
            ax.text(b.get_x() + b.get_width() / 2, v + 2,
                    f"{round(v * n / 100)}/{n}\n{v:.0f}%", ha="center", va="bottom", fontsize=8.5)
        ax.set_xticks(range(3), [lbl for _, lbl, _ in COND], fontsize=8)
        ax.set_ylim(0, 125)
        ax.set_yticks([0, 25, 50, 75, 100])
        ax.set_ylabel("% of instances")
        ax.set_title(title.format(n=n), fontsize=10)
        if inset and d is t["intent_all"]:
            lo, hi = d["gap_ci"]
            ax.text(0.03, 0.97, f"G = {d['gap_recovery']:.2f}\n95% CI {lo:.2f} to {hi:.2f}\n"
                    f"p = {d['mcnemar_p']:.2f}", transform=ax.transAxes, va="top",
                    fontsize=7.8, bbox=dict(fc="white", ec=GREY, lw=0.6, pad=2.5))
    fig.tight_layout()
    _save(fig, name)


def fig_funnel(study_key: str = "v2", name: str = "fig8_funnel.png") -> None:
    f = N[study_key]["funnel"]
    steps = [
        ("Instances reviewed in all three conditions", N[study_key]["complete_triples"], GREY),
        ("Floor failed to recover intent", f["floor_misses"], NAVY),
        ("... and the detector asked", f["detector_asked"], ORANGE),
        ("... and the author answered", f["author_answered"], ORANGE),
        ("... and the treatment then recovered intent", f["treatment_recovered"], GREEN),
    ]
    fig, ax = plt.subplots(figsize=(8.6, 3.0))
    top = steps[0][1]
    for i, (label, v, color) in enumerate(steps):
        y = len(steps) - 1 - i
        ax.barh(y, v, color=color, height=0.62)
        ax.text(v + top * 0.012, y, f"{v}", va="center", fontsize=10, fontweight="bold")
        ax.text(-top * 0.015, y, label, va="center", ha="right", fontsize=9.5)
    ax.set_xlim(0, top * 1.08)
    ax.set_yticks([])
    ax.spines["left"].set_visible(False)
    ax.set_xlabel("instances")
    ax.set_title("Where the clarification effect is lost", loc="left")
    _save(fig, name)


def fig_detectors() -> None:
    det = N["detectors"]
    names = [n for n in ("heuristic", "sampling", "perturbation") if n in det]
    fig, ax = plt.subplots(figsize=(7.4, 3.2))
    w = 0.36
    for i, n in enumerate(names):
        s, f = det[n]["mean_score_stripped"], det[n]["mean_score_full"]
        ax.bar(i - w / 2, s, w, color=ORANGE, label="intent withheld" if i == 0 else None)
        ax.bar(i + w / 2, f, w, color=NAVY, label="full context" if i == 0 else None)
        box = dict(fc="white", ec="none", pad=0.6)
        ax.text(i - w / 2, s + 0.025, f"{s:.2f}", ha="center", fontsize=8.5, bbox=box, zorder=5)
        ax.text(i + w / 2, f + 0.025, f"{f:.2f}", ha="center", fontsize=8.5, bbox=box, zorder=5)
    thresholds = {"heuristic": 0.50, "sampling": 0.35, "perturbation": 0.35}
    for i, n in enumerate(names):
        ax.hlines(thresholds[n], i - 0.45, i + 0.45, colors="black", linestyles="--", lw=1,
                  zorder=3)
    ax.plot([], [], "k--", lw=1, label="default threshold")
    labels = [f"{n}\n(n={det[n]['n_decisions']}, ask rate {det[n]['ask_rate'] * 100:.0f}%)"
              for n in names]
    ax.set_xticks(range(len(names)), labels, fontsize=8.5)
    ax.set_ylim(0, 1.05)
    ax.set_ylabel("mean ambiguity score")
    ax.set_title("Detector scores: does the score separate the two contexts?", loc="left")
    ax.legend(frameon=False, fontsize=8.5, loc="upper left", ncol=3)
    _save(fig, "fig9_detectors.png")


def fig_mutants() -> None:
    m = N["mutants"]["by_status"]
    order = [("verified", "verified: golden passes,\nmutant fails", GREEN),
             ("no_mutation_applies", "no operator applies\nto the added lines", GREY),
             ("environment_cannot_run_tests", "tests cannot run\nin the environment", "#A5A5A5"),
             ("every_mutant_survived", "every mutant survived\n(tests did not catch it)", ORANGE)]
    fig, ax = plt.subplots(figsize=(7.4, 2.8))
    vals = [m.get(k, 0) for k, _, _ in order]
    bars = ax.barh(range(len(order))[::-1], vals, color=[c for _, _, c in order], height=0.6)
    for b, v in zip(bars, vals):
        ax.text(v + 0.6, b.get_y() + b.get_height() / 2, str(v), va="center", fontweight="bold")
    ax.set_yticks(range(len(order))[::-1], [lbl for _, lbl, _ in order], fontsize=8.5)
    ax.set_xlabel(f"sympy instances (of {N['mutants']['attempted']})")
    ax.set_title("Execution-verified mutant yield", loc="left")
    _save(fig, "fig10_mutants.png")


def fig_design() -> None:
    """The 2 x 3 study design as a grid of what each cell is shown."""
    fig, ax = plt.subplots(figsize=(9.2, 3.6))
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 4.2)
    ax.axis("off")
    cols = [("Floor", "issue, PR text, commit\nmessages and added\ncomments removed", GREY),
            ("Treatment", "same stripped context\n+ detector may ask the\nsimulated author", ORANGE),
            ("Ceiling", "full context:\nissue, messages\nand comments", NAVY)]
    rows = [("Golden patch\n(accepted fix)", "measures intent recovery\nand false alarms"),
            ("Verified mutant\n(injected defect)", "measures intent recovery\nand defect detection")]
    for j, (name, desc, color) in enumerate(cols):
        x = 2.4 + j * 2.55
        ax.add_patch(FancyBboxPatch((x, 3.05), 2.3, 1.0, boxstyle="round,pad=0.02",
                                    fc=color, ec="none"))
        ax.text(x + 1.15, 3.78, name, ha="center", va="center", color="white",
                fontweight="bold", fontsize=10.5)
        ax.text(x + 1.15, 3.33, desc, ha="center", va="center", color="white", fontsize=7.4)
    for i, (name, desc) in enumerate(rows):
        y = 1.7 - i * 1.45
        ax.add_patch(FancyBboxPatch((0.05, y), 2.15, 1.2, boxstyle="round,pad=0.02",
                                    fc=LIGHT, ec=NAVY))
        ax.text(1.12, y + 0.78, name, ha="center", va="center", fontweight="bold", fontsize=9)
        ax.text(1.12, y + 0.27, desc, ha="center", va="center", fontsize=7.2)
        for j in range(3):
            x = 2.4 + j * 2.55
            ax.add_patch(FancyBboxPatch((x, y), 2.3, 1.2, boxstyle="round,pad=0.02",
                                        fc="white", ec=cols[j][2], lw=1.3))
            ax.text(x + 1.15, y + 0.6, "same reviewer model,\nsame prompt template",
                    ha="center", va="center", fontsize=7.6, color="#404040")
    ax.text(5.0, -0.12, "Floor and treatment see byte-identical code; they differ only in "
            "whether Stages 2-3 run.", ha="center", fontsize=8, style="italic")
    _save(fig, "fig11_design.png")


# ------------------------------------------------- judges (v3 additions)

_METRICS = [("intent_recovered", "Intent recovered"), ("defect_caught", "Defect caught"),
            ("false_alarm", "False alarm")]


def fig_judges() -> None:
    """Kappa between pairs of AI judges. AI-vs-AI agreement, not human validation."""
    from matplotlib.colors import LinearSegmentedColormap

    J = N["judges"]
    rows = [("v2: gemma-4-31b-it vs\nClaude agent", J["v2_pairs"]["api_vs_agent"]),
            ("v2: Gemini web vs\nClaude agent (sample)", J["v2_pairs"]["gemini_vs_agent"]),
            ("v2: Gemini web vs\ngemma-4-31b-it (sample)", J["v2_pairs"]["gemini_vs_api"]),
            ("v3: llama3.2:3b vs\nClaude agent", J["v3_pairs"]["llama_vs_agent"])]
    cmap = LinearSegmentedColormap.from_list("kappa", [ORANGE, "#FFFFFF", NAVY])
    fig, ax = plt.subplots(figsize=(7.6, 3.6))
    for i, (_, pair) in enumerate(rows):
        for j, (m, _) in enumerate(_METRICS):
            c = pair[m]
            k = c["kappa"]
            ax.add_patch(plt.Rectangle((j, len(rows) - 1 - i), 1, 1, fc=cmap((k + 1) / 2),
                                       ec="white", lw=2))
            ax.text(j + 0.5, len(rows) - 1 - i + 0.5,
                    f"κ {k:.2f}\n{c['percent_agreement'] * 100:.0f}% agree\nn = {c['n']}",
                    ha="center", va="center", fontsize=8.3,
                    color="white" if abs(k) > 0.55 else "#202020")
    ax.set_xlim(0, len(_METRICS))
    ax.set_ylim(0, len(rows))
    ax.set_xticks([j + 0.5 for j in range(len(_METRICS))], [lbl for _, lbl in _METRICS],
                  fontsize=9)
    ax.xaxis.tick_top()
    ax.set_yticks([len(rows) - 1 - i + 0.5 for i in range(len(rows))],
                  [lbl for lbl, _ in rows], fontsize=8.3)
    ax.tick_params(length=0)
    for sp in ax.spines.values():
        sp.set_visible(False)
    ax.set_title("Agreement between AI judges (Cohen's κ)", loc="left", pad=26)
    _save(fig, "fig16_judges.png")


def fig_judge_robustness() -> None:
    """Intent gap recovery G (95% CI) under each judge. Hatched = judge unusable."""
    items = [("v2\ngemma-4-31b-it", N["v2"], False),
             ("v2\nClaude agent", N["v2_agent_judge"], False),
             ("v3\nClaude agent", N["v3_local"], False),
             ("v3\nllama3.2:3b", N["v3_local_llama_judge"], True)]
    fig, ax = plt.subplots(figsize=(7.2, 3.3))
    for i, (lbl, st, bad) in enumerate(items):
        d = st["tests"]["intent_all"]
        g, (lo, hi) = d["gap_recovery"], d["gap_ci"]
        if g is None:
            continue
        ax.bar(i, g, 0.55, color=GREY if bad else ORANGE, hatch="//" if bad else None,
               edgecolor="white" if bad else "none",
               label=("unreliable judge (never flagged a false alarm; kappa near 0)" if bad
                      else ("usable judge" if i == 0 else None)))
        ax.errorbar(i, g, yerr=[[g - lo], [hi - g]], color="black", capsize=4, lw=1)
        ax.text(i + 0.32, g, f"{g:.2f}", fontsize=8.5, va="center")
    ax.axhline(0, color="black", lw=0.8)
    ax.set_xticks(range(len(items)), [lbl for lbl, _, _ in items], fontsize=8.5)
    ax.set_ylabel("gap recovery G")
    ax.legend(frameon=False, fontsize=8, loc="upper center", bbox_to_anchor=(0.5, -0.2), ncol=2)
    ax.set_title("Effect size depends on the judge; every interval reaches zero", loc="left")
    _save(fig, "fig17_judge_robustness.png")


# ----------------------------------------------------------------- demo

def _terminal(lines: list[str], name: str, title: str, width: float = 9.0) -> None:
    h = 0.18 * len(lines) + 0.55
    fig = plt.figure(figsize=(width, h))
    fig.patch.set_facecolor("#1E1E1E")
    ax = fig.add_axes([0, 0, 1, 1])
    ax.axis("off")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.text(0.012, 1 - 0.18 / h, title, color="#9CDCFE", family="monospace", fontsize=8.5,
            va="top", fontweight="bold")
    for i, line in enumerate(lines):
        color = "#D4D4D4"
        if line.startswith("$"):
            color = "#DCDCAA"
        elif line.startswith("+"):
            color = "#6A9955"
        elif line.startswith("-") and not line.startswith("---"):
            color = "#F48771"
        elif re.match(r"^(decision|\[stage|\[judge|──)", line):
            color = "#4FC1FF"
        ax.text(0.012, 1 - (0.42 + 0.18 * i) / h, line, color=color, family="monospace",
                fontsize=7.6, va="top")
    fig.savefig(OUT / name, facecolor=fig.get_facecolor())
    plt.close(fig)
    print("wrote", OUT / name)


def _wrap(text: str, n: int = 108) -> list[str]:
    import textwrap
    out = []
    for line in text.splitlines():
        out.extend(textwrap.wrap(line, n, subsequent_indent="           ") or [""])
    return out


def _cli() -> str:
    """The project's own CLI: the venv script on Windows or POSIX, else whatever is on PATH."""
    for cand in (ROOT / ".venv/Scripts/clarifyreview.exe", ROOT / ".venv/bin/clarifyreview",
                 Path(sys.executable).with_name("clarifyreview.exe"),
                 Path(sys.executable).with_name("clarifyreview")):
        if cand.exists():
            return str(cand)
    found = shutil.which("clarifyreview")
    if not found:
        raise SystemExit("clarifyreview CLI not found: pip install -e . first")
    return found


def fig_demo() -> None:
    cr = _cli()
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}

    def run(*args: str) -> str:
        res = subprocess.run([cr, *args], cwd=ROOT, capture_output=True, text=True,
                             encoding="utf-8", env=env)
        return res.stdout.strip()

    ask = run("detect", "--diff", "examples/ambiguous.diff", "--commit-msg", "fix")
    proceed = run("detect", "--diff", "examples/clear.diff", "--commit-msg",
                  "Trim surrounding whitespace before slugifying so pasted CMS titles "
                  "do not produce trailing dashes")
    diff = (ROOT / "examples/ambiguous.diff").read_text(encoding="utf-8").strip()
    lines = (diff.splitlines() + ["", "$ clarifyreview detect --diff examples/ambiguous.diff "
             "--commit-msg 'fix'"] + _wrap(ask) + ["", "$ clarifyreview detect --diff "
             "examples/clear.diff --commit-msg 'Trim surrounding whitespace ...'"] + _wrap(proceed))
    _terminal(lines, "fig12_demo_detect.png", "Stage 2 on two pull requests: ASK, then PROCEED")

    replay = run("replay", "--db", "data/study_v2.db")
    _terminal(_wrap(replay), "fig13_demo_replay.png",
              "$ clarifyreview replay   (recorded study run, all four stages)", width=9.6)

    tests = subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=ROOT,
                           capture_output=True, text=True, encoding="utf-8",
                           env=env).stdout.strip().splitlines()
    files = sorted(p.name for p in (ROOT / "tests").glob("test_*.py"))
    _terminal(["$ pytest -q"] + tests[-3:] + ["", f"test files ({len(files)}):"]
              + [f"  {f}" for f in files], "fig14_tests.png", "The automated test suite",
              width=7.0)


def main() -> int:
    fig_results()
    fig_funnel()
    fig_detectors()
    fig_mutants()
    fig_design()
    # Added for the v3 replication and the judge check; numbered after the old ones.
    if N.get("v3_local", {}).get("available"):
        fig_results("v3_local", "fig15_v3_results.png", inset=True)
        fig_funnel("v3_local", "fig18_v3_funnel.png")
    if N.get("judges", {}).get("available"):
        fig_judges()
        fig_judge_robustness()
    fig_demo()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
