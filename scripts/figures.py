import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import FancyBboxPatch
import numpy as np
import pandas as pd
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
GOALS = [
    "cash_substitution", "financial_inclusion", "sovereignty_competition",
    "payment_modernization", "monetary_transmission", "state_control",
]
LABELS = [
    "Cash substitution", "Financial inclusion", "Sovereignty & competition",
    "Payment modernisation", "Monetary transmission", "State control",
]
COLORS = ["#4C78A8", "#59A14F", "#E15759", "#F28E2B", "#B07AA1", "#79706E"]
TITLE = dict(zip(GOALS, LABELS))
COLOR = dict(zip(GOALS, COLORS))
SHORT = {
    "International / cross-border bodies (UN-system)": "International bodies",
    "Banco Central del Paraguay (2024 design paper) — composite": "Paraguay (2024 paper)",
    "Eastern Caribbean (OECS / ECCU)": "Eastern Caribbean (ECCU)",
}


def save_rgb(fig, path, dpi):
    fig.savefig(path, dpi=dpi, facecolor="white")
    plt.close(fig)
    with Image.open(path) as image:
        rgba = image.convert("RGBA")
        background = Image.new("RGB", rgba.size, "white")
        background.paste(rgba, mask=rgba.getchannel("A"))
        background.save(path)


def correlations(audit):
    rows = [
        ("vdem", "Democracy\n(V-Dem lib-dem)"), ("cbi", "Central bank\nindependence"),
        ("shadow", "Informal economy\n(% GDP)"), ("basel", "AML risk\n(Basel score)"),
    ]
    fig, axis = plt.subplots(figsize=(9.2, 5.6), facecolor="white")
    for y, (key, _) in zip(range(3, -1, -1), rows):
        vocabulary = audit["pairwise"]["vocabulary"][key]
        posture = audit["pairwise"]["commitment"][key]
        axis.plot(vocabulary["ci"], [y + 0.13] * 2, color="#9AA0A6", lw=2.2, solid_capstyle="round")
        axis.plot(posture["ci"], [y - 0.13] * 2, color="#C0392B", lw=2.2, solid_capstyle="round")
        axis.scatter(vocabulary["r"], y + 0.13, s=150, color="#9AA0A6", edgecolors="white", linewidths=1.2, zorder=3)
        axis.scatter(posture["r"], y - 0.13, s=160, color="#C0392B", edgecolors="white", linewidths=1.2, zorder=3)
        axis.text(vocabulary["r"], y + 0.30, f'{vocabulary["r"]:+.2f}', ha="center", fontsize=9, color="#666")
        axis.text(posture["r"], y - 0.44, f'{posture["r"]:+.2f}', ha="center", fontsize=9, color="#C0392B", fontweight="bold")
    axis.axvline(0, color="#999", lw=1, ls=":")
    axis.set_yticks(range(3, -1, -1), [label for _, label in rows], fontsize=10)
    axis.set(xlim=(-0.75, 0.75), ylim=(-0.75, 3.7))
    axis.set_xlabel("Correlation with privacy measure (points) and bootstrap 95 % CI (bars)", fontsize=10.5)
    for spine in ["top", "right", "left"]:
        axis.spines[spine].set_visible(False)
    axis.legend(handles=[
        Line2D([0], [0], marker="o", color="w", markerfacecolor="#9AA0A6", markersize=11, label="privacy-family share"),
        Line2D([0], [0], marker="o", color="w", markerfacecolor="#C0392B", markersize=11, label="documented privacy posture"),
    ], loc="upper right", frameon=False, fontsize=9.5)
    fig.tight_layout()
    save_rgb(fig, ROOT / "figures/correlations.png", 200)


def composition(scores):
    values = scores[[f"fz_{goal}" for goal in GOALS]].to_numpy()
    shares = values / values.sum(axis=1, keepdims=True)
    order = scores.assign(_order=scores["dominant_centre"].map(dict(zip(GOALS, range(6))))).sort_values(
        ["_order", "dominant_score"], ascending=[True, False]
    ).index
    shares = shares[order]
    names = scores.loc[order, "country"].fillna(scores.loc[order, "jur"])
    fig, axis = plt.subplots(figsize=(7.6, 10), facecolor="white")
    left = np.zeros(len(shares))
    for i, label in enumerate(LABELS):
        axis.barh(range(len(shares))[::-1], shares[:, i], left=left, color=COLORS[i], height=0.82, label=label)
        left += shares[:, i]
    axis.set_yticks(range(len(shares))[::-1], [SHORT.get(name, name)[:24].rstrip() for name in names], fontsize=7.4)
    axis.set_xlim(0, 1)
    axis.set_xlabel("Share of documented-purpose weight across the six centres", fontsize=9.5)
    axis.legend(loc="upper center", bbox_to_anchor=(0.5, -0.045), ncol=3, frameon=False, fontsize=8.4)
    axis.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    save_rgb(fig, ROOT / "figures/composition.png", 240)


def pastel(color, fraction=0.82):
    rgb = [int(color[i:i + 2], 16) for i in (1, 3, 5)]
    return tuple((value + (255 - value) * fraction) / 255 for value in rgb)


def centres(scores):
    scores = scores.copy()
    scores["mixed_case"] = scores["mixed_case"].astype(str).str.lower().isin(["true", "1"])
    order = ["sovereignty_competition", "state_control", "payment_modernization",
             "financial_inclusion", "monetary_transmission", "cash_substitution"]
    fig, axes = plt.subplots(3, 2, figsize=(10.5, 11), facecolor="white")
    for axis, goal in zip(axes.flat, order):
        axis.set(xlim=(0, 1), ylim=(0, 1))
        axis.axis("off")
        axis.add_patch(FancyBboxPatch((0.01, 0.01), 0.98, 0.98,
                       boxstyle="round,pad=0.012,rounding_size=0.025",
                       facecolor=pastel(COLOR[goal]), edgecolor=COLOR[goal], linewidth=1.6))
        group = scores[scores["dominant_centre"] == goal].sort_values("dominant_score", ascending=False)
        axis.text(0.06, 0.925, TITLE[goal], fontsize=14.5, fontweight="bold", color=COLOR[goal], va="center")
        axis.text(0.94, 0.925, str(len(group)), fontsize=14.5, fontweight="bold", color=COLOR[goal], va="center", ha="right")
        if goal == "cash_substitution":
            axis.text(0.06, 0.83, "No dominant jurisdiction after the\nstate-facing privacy gate.", fontsize=9, style="italic", color="#333", va="top")
            invoked = scores[scores["fz_cash_substitution"] > 0.5].sort_values("fz_cash_substitution", ascending=False)
            axis.text(0.06, 0.64, f"Strong invokers ({len(invoked)}), actual dominant purpose:", fontsize=8.6, color="#555", va="top")
            for i, row in enumerate(invoked.itertuples()):
                column, line = divmod(i, 7)
                name = SHORT.get(str(row.country or row.jur), str(row.country or row.jur))[:20].rstrip()
                axis.text(0.06 + column * 0.48, 0.575 - line * 0.072,
                          f"{name}  ({TITLE[row.dominant_centre].split(' ')[0]})", fontsize=8.6, color="#666", va="top")
        else:
            for i, row in enumerate(group.itertuples()):
                column, line = divmod(i, 6)
                name = SHORT.get(str(row.country or row.jur), str(row.country or row.jur))[:25].rstrip()
                axis.text(0.06 + column * 0.48, 0.82 - line * 0.115,
                          name + (" °" if row.mixed_case else ""), fontsize=10.2, color="#222", va="top")
    fig.suptitle("CBDC projects across six purpose centres\nDominant documented purpose by jurisdiction", fontsize=11.5, y=0.995)
    fig.text(0.055, 0.006, "° mixed case: second purpose within 0.10 of the dominant", fontsize=9, color="#444")
    fig.tight_layout(rect=[0, 0.015, 1, 0.95])
    save_rgb(fig, ROOT / "figures/centres.png", 200)


def main():
    scores = pd.read_csv(ROOT / "results/scores.csv", keep_default_na=False)
    audit = json.loads((ROOT / "results/audit.json").read_text(encoding="utf-8"))
    correlations(audit)
    composition(scores)
    centres(scores)
    print("figures: correlations, composition, centres")


if __name__ == "__main__":
    main()
