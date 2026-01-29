#!/usr/bin/env python3
"""
Plot extracted virus data for visual verification against original charts.
"""

import json
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import Patch
import numpy as np

# Output directory
OUTPUT_DIR = Path(__file__).parent / "output"


def load_data():
    """Load extracted JSON data."""
    with open(OUTPUT_DIR / "heatmap_data.json", encoding="utf-8") as f:
        heatmap = json.load(f)
    with open(OUTPUT_DIR / "bar_chart_data.json", encoding="utf-8") as f:
        bar_chart = json.load(f)
    return heatmap, bar_chart


def plot_heatmap(data: dict, ax: plt.Axes):
    """Plot the heatmap similar to original."""
    weeks = data["weeks"]

    # Virus order matching original heatmap (top to bottom)
    virus_order = ["Covid19", "Influenza", "Entero", "MPV", "RSV", "RH", "AD", "Para", "Corona"]
    # Filter to only viruses present in data
    viruses = [v for v in virus_order if v in data["viruses"]]

    # Build matrix in correct order
    matrix = []
    for virus in viruses:
        row = [data["data"][virus].get(week, 0) for week in weeks]
        matrix.append(row)

    matrix = np.array(matrix)

    # Plot with yellow-orange-red colormap like original
    im = ax.imshow(matrix, aspect="auto", cmap="YlOrRd", vmin=0, vmax=120)

    # Y-axis labels (virus names)
    ax.set_yticks(range(len(viruses)))
    ax.set_yticklabels(viruses, fontsize=9)

    # X-axis: show every 2nd week label like original
    tick_positions = range(0, len(weeks), 2)
    ax.set_xticks(tick_positions)
    ax.set_xticklabels([weeks[i] for i in tick_positions], rotation=45, ha="right", fontsize=8)

    ax.set_title("Virusnachweise im Sentinelsystem (Rekonstruiert)", fontsize=12, fontweight='bold')
    ax.set_xlabel("Kalenderwoche", fontsize=10)

    # Colorbar on the right, inside the figure
    cbar = plt.colorbar(im, ax=ax, shrink=0.8, pad=0.02)
    cbar.set_label("Fallzahl", fontsize=10)


def plot_bar_chart(data: dict, ax: plt.Axes):
    """Plot stacked bar chart similar to original."""
    weeks = data["weeks"]

    # Virus order matching original SVG stacking (bottom to top)
    virus_order = [
        "Entero", "Inf_A", "Inf_B", "Inf_C", "Metapneumo_V",
        "RSV", "Rhino", "Adeno", "ParaInfluenza", "Corona", "Covid-19"
    ]
    # Filter to only viruses present in data
    viruses = [v for v in virus_order if v in data["viruses"]]

    # Colors matching original SVG legend
    colors = {
        "Inf_A": "#E63946",
        "Inf_B": "#E07B00",
        "Inf_C": "#A0522D",
        "Metapneumo_V": "#6C757D",
        "Covid-19": "#FFAA00",
        "Corona": "#16A085",
        "RSV": "#7D47BC",
        "Rhino": "#1CA9C9",
        "Adeno": "#556B2F",
        "ParaInfluenza": "#1D3557",
        "Entero": "#5A2E18",
    }

    # Labels matching original
    labels = {
        "Inf_A": "Inf A",
        "Inf_B": "Inf B",
        "Inf_C": "Inf C",
        "Metapneumo_V": "Metapneumo V.",
        "Covid-19": "Covid-19",
        "Corona": "Corona",
        "RSV": "RSV",
        "Rhino": "Rhino",
        "Adeno": "Adeno",
        "ParaInfluenza": "ParaInfluenza",
        "Entero": "Entero",
    }

    x = np.arange(len(weeks))
    width = 0.8

    # Plot Einsendungen as gray area in background (right y-axis)
    ax2 = ax.twinx()
    if "einsendungen" in data:
        einsendungen_values = [data["einsendungen"].get(week, 0) for week in weeks]
        ax2.fill_between(x, 0, einsendungen_values, alpha=0.4, color="#e4e4e4")
        ax2.set_ylabel("N Einsendungen", color="gray", fontsize=10)
        ax2.tick_params(axis="y", labelcolor="gray")
        ax2.set_ylim(0, 420)

    # Stack bars (on primary axis)
    bars = []
    bottom = np.zeros(len(weeks))
    for virus in viruses:
        values = [data["data"][week].get(virus, 0) for week in weeks]
        bar = ax.bar(x, values, width, bottom=bottom, label=labels.get(virus, virus),
                     color=colors.get(virus, "#888"))
        bars.append(bar)
        bottom += np.array(values)

    # Labels
    ax.set_xticks(x[::2])  # Every 2nd week like original
    ax.set_xticklabels([weeks[i] for i in range(0, len(weeks), 2)], rotation=55, ha="right", fontsize=8)
    ax.set_ylabel("N Virusnachweise", fontsize=10)
    ax.set_ylim(0, 350)

    # Title
    ax.set_title("Virusnachweise im Sentinelsystem (Rekonstruiert)", fontsize=12, fontweight='bold')

    # Add Einsendungen to legend (gray patch)
    einsendungen_patch = Patch(facecolor='#e4e4e4', alpha=0.4, label='Einsendungen')

    # Get bar handles and add Einsendungen patch at the end
    handles, legend_labels = ax.get_legend_handles_labels()
    handles.append(einsendungen_patch)
    legend_labels.append('Einsendungen')

    # Current order from stacking: Entero(0), Inf_A(1), Inf_B(2), Inf_C(3), Metapneumo_V(4),
    #                              RSV(5), Rhino(6), Adeno(7), Parainfluenza(8), Corona(9), Covid-19(10), Einsendungen(11)
    # Desired legend order:
    # Row 1: Inf_A, Inf_B, Inf_C, Metapneumo_V, Covid-19, Corona
    # Row 2: RSV, Rhino, Adeno, Parainfluenza, Entero, Einsendungen
    legend_order = [1, 2, 3, 4, 10, 9, 5, 6, 7, 8, 0, 11]  # Map to desired legend order

    # Reorder handles/labels to match legend order
    handles = [handles[i] for i in legend_order]
    legend_labels = [legend_labels[i] for i in legend_order]

    # Reorder for row-major layout (matplotlib fills column-major with ncol)
    row1 = list(range(6))       # 0,1,2,3,4,5
    row2 = list(range(6, 12))   # 6,7,8,9,10,11
    reordered_indices = []
    for i in range(6):
        reordered_indices.append(row1[i])
        reordered_indices.append(row2[i])
    handles = [handles[i] for i in reordered_indices]
    legend_labels = [legend_labels[i] for i in reordered_indices]

    # Legend inside plot, upper left, in 2 rows matching original order
    ax.legend(handles, legend_labels, loc='upper left', ncol=6, fontsize=8,
              frameon=True, framealpha=0.9, columnspacing=1)

    ax.set_zorder(ax2.get_zorder() + 1)
    ax.patch.set_visible(False)


def main():
    """Generate comparison plots."""
    heatmap_data, bar_data = load_data()

    # Plot 1: Heatmap (wider aspect ratio like original)
    fig1, ax1 = plt.subplots(figsize=(16, 5))
    plot_heatmap(heatmap_data, ax1)
    plt.subplots_adjust(bottom=0.18, right=0.95)  # Space for rotated labels
    output_file1 = OUTPUT_DIR / "verification_heatmap.png"
    plt.savefig(output_file1, dpi=150)
    print(f"Saved: {output_file1}")
    plt.close(fig1)

    # Plot 2: Bar Chart (aspect ratio similar to original SVG 768x440)
    fig2, ax2 = plt.subplots(figsize=(16, 6))
    plot_bar_chart(bar_data, ax2)
    plt.subplots_adjust(top=0.92, bottom=0.15)  # Legend is inside plot now
    output_file2 = OUTPUT_DIR / "verification_barchart.png"
    plt.savefig(output_file2, dpi=150)
    print(f"Saved: {output_file2}")
    plt.close(fig2)


if __name__ == "__main__":
    main()
