"""Generate every results figure used by the report, the deck and the paper.

Reads only paper/numbers.json, the experiment log and the demo output, so a
re-run after any new experiment regenerates figures that agree with the text.

    .venv/bin/pip install -e '.[docs]'
    .venv/bin/python -m paper.collect
    .venv/bin/python docs/figures/make_figures.py

The design figures from Review 2 (Gantt, architecture, DFD, use case, class,
sequence) are static and live alongside these as fig1_* to fig6_*.
"""

from __future__ import annotations

import json
import re
import sqlite3
import subprocess
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyBboxPatch  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
N = json.loads((ROOT / "paper/numbers.json").read_text())

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

def fig_results() -> None:
    t = N["v2"]["tests"]
    panels = [
        ("Intent recovered\n(all 36 instances)", t["intent_all"], 36),
        ("Injected defect caught\n(12 verified mutants)", t["defect_mutant"], 12),
        ("False alarm raised\n(24 correct patches)", t["false_alarm_golden"], 24),
    ]
    key = {"stripped_plain": "floor", "stripped_clarify": "treatment", "full_plain": "ceiling"}
    fig, axes = plt.subplots(1, 3, figsize=(10, 3.4))
    for ax, (title, d, n) in zip(axes, panels):
        vals = [d[key[c]] * 100 for c, _, _ in COND]
        bars = ax.bar(range(3), vals, color=[c for _, _, c in COND], width=0.62)
        for b, v in zip(bars, vals):
            ax.text(b.get_x() + b.get_width() / 2, v + 2,
                    f"{round(v * n / 100)}/{n}\n{v:.0f}%", ha="center", va="bottom", fontsize=8.5)
        ax.set_xticks(range(3), [lbl for _, lbl, _ in COND], fontsize=8)
        ax.set_ylim(0, 125)
        ax.set_yticks([0, 25, 50, 75, 100])
        ax.set_ylabel("% of instances")
        ax.set_title(title, fontsize=10)
    fig.tight_layout()
    _save(fig, "fig7_results.png")


def fig_funnel() -> None:
    f = N["v2"]["funnel"]
    steps = [
        ("Instances reviewed in all three conditions", N["v2"]["complete_triples"], GREY),
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
    _save(fig, "fig8_funnel.png")


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


def fig_demo() -> None:
    cr = str(ROOT / ".venv/bin/clarifyreview")

    def run(*args: str) -> str:
        res = subprocess.run([cr, *args], cwd=ROOT, capture_output=True, text=True)
        return res.stdout.strip()

    ask = run("detect", "--diff", "examples/ambiguous.diff", "--commit-msg", "fix")
    proceed = run("detect", "--diff", "examples/clear.diff", "--commit-msg",
                  "Trim surrounding whitespace before slugifying so pasted CMS titles "
                  "do not produce trailing dashes")
    diff = (ROOT / "examples/ambiguous.diff").read_text().strip()
    lines = (diff.splitlines() + ["", "$ clarifyreview detect --diff examples/ambiguous.diff "
             "--commit-msg 'fix'"] + _wrap(ask) + ["", "$ clarifyreview detect --diff "
             "examples/clear.diff --commit-msg 'Trim surrounding whitespace ...'"] + _wrap(proceed))
    _terminal(lines, "fig12_demo_detect.png", "Stage 2 on two pull requests: ASK, then PROCEED")

    replay = run("replay", "--db", "data/study_v2.db")
    _terminal(_wrap(replay), "fig13_demo_replay.png",
              "$ clarifyreview replay   (recorded study run, all four stages)", width=9.6)

    tests = subprocess.run([str(ROOT / ".venv/bin/python"), "-m", "pytest", "-q"], cwd=ROOT,
                           capture_output=True, text=True).stdout.strip().splitlines()
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
    fig_demo()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
