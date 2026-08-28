#!/usr/bin/env python3
"""Render a Fig. 24-style loop-decoupling summary as a PNG image."""

from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
APPLICATIONS = [
    ("database_hj_m", "HJ-P"),
    ("database_gb_m", "GB"),
    ("graph_bfs_queue", "BFS"),
    ("graph_sssp_queue", "SSSP"),
    ("graph_mst_queue", "MST"),
    ("network_ipv4_m", "IPv4"),
]
PANELS = [
    ("coverage", "Coverage", 1.0),
    ("timeliness", "Timeliness", 1.0),
    ("speedup_over_nopf", "Speedup", None),
]


def load(path: Path) -> dict[tuple[str, str], float]:
    values: dict[tuple[str, str], float] = {}
    with path.open(newline="", encoding="utf-8") as stream:
        for row in csv.DictReader(stream):
            if row["application"] == "overall":
                continue
            for metric, _, _ in PANELS:
                values[(row["application"], row["variant"], metric)] = float(
                    row[metric]
                )
    return values


def font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    path = Path("/usr/share/fonts/truetype/dejavu") / name
    try:
        return ImageFont.truetype(str(path), size)
    except OSError:
        return ImageFont.load_default()


def centered_text(
    draw: ImageDraw.ImageDraw,
    xy: tuple[float, float],
    value: str,
    selected_font: ImageFont.ImageFont,
) -> None:
    draw.text(xy, value, fill="#111111", font=selected_font, anchor="mm")


def render(
    values: dict[tuple[str, str], float],
    output: Path,
    profile_label: str = "",
) -> None:
    scale = 2
    width, height = 960 * scale, 330 * scale
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    margin_left, margin_top = 48 * scale, 48 * scale
    panel_width, plot_height, plot_width = 292 * scale, 220 * scale, 250 * scale
    normal, small, heading = font(14 * scale), font(12 * scale), font(14 * scale, True)

    if profile_label:
        draw.text(
            (48 * scale, 14 * scale),
            profile_label,
            fill="#111111",
            font=heading,
            anchor="la",
        )
    legend_y = 21 * scale
    draw.rectangle(
        (380 * scale, 14 * scale, 394 * scale, 28 * scale),
        fill="#c8d0d6",
        outline="#263238",
        width=scale,
    )
    draw.text(
        (400 * scale, legend_y),
        "No loop decoupling",
        fill="#111111",
        font=normal,
        anchor="lm",
    )
    draw.rectangle(
        (580 * scale, 14 * scale, 594 * scale, 28 * scale),
        fill="#17232b",
    )
    draw.text(
        (600 * scale, legend_y),
        "Loop decoupling",
        fill="#111111",
        font=normal,
        anchor="lm",
    )

    for panel_index, (metric, title, fixed_max) in enumerate(PANELS):
        x0 = margin_left + panel_index * panel_width
        y0 = margin_top + plot_height
        panel_values = [
            values.get((application, variant, metric), 0.0)
            for application, _ in APPLICATIONS
            for variant in ("no_loop", "full")
        ]
        y_max = fixed_max or max(3.0, math.ceil(max(panel_values) * 2) / 2)
        for tick in (0.0, y_max / 2, y_max):
            y = y0 - tick / y_max * plot_height
            draw.line(
                (x0, y, x0 + plot_width, y),
                fill="#bbbbbb",
                width=scale,
            )
            label = f"{tick * 100:.0f}%" if fixed_max else f"{tick:g}"
            draw.text(
                (x0 - 7 * scale, y),
                label,
                fill="#111111",
                font=small,
                anchor="rm",
            )
        draw.line((x0, margin_top, x0, y0), fill="#111111", width=2 * scale)
        draw.line((x0, y0, x0 + plot_width, y0), fill="#111111", width=2 * scale)
        centered_text(
            draw,
            (x0 + plot_width / 2, height - 14 * scale),
            f"({chr(ord('a') + panel_index)}) {title}",
            normal,
        )

        group_width = plot_width / len(APPLICATIONS)
        bar_width = 15 * scale
        for app_index, (application, label) in enumerate(APPLICATIONS):
            center = x0 + group_width * (app_index + 0.5)
            for variant_index, variant in enumerate(("no_loop", "full")):
                value = values.get((application, variant, metric), 0.0)
                bar_height = max(0.0, value / y_max * plot_height)
                x = center + (variant_index - 1) * bar_width
                y = y0 - bar_height
                fill = "#c8d0d6" if variant == "no_loop" else "#17232b"
                draw.rectangle(
                    (x, y, x + bar_width, y0),
                    fill=fill,
                    outline="#263238",
                    width=scale,
                )
            centered_text(draw, (center, y0 + 18 * scale), label, small)

    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, format="PNG", optimize=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-profile", choices=("fast", "full"), default="fast")
    parser.add_argument("--input", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--profile-label", default="")
    args = parser.parse_args()
    root = ROOT / "results" / args.run_profile / "analysis"
    input_path = args.input or root / "mechanism_summary.csv"
    output_path = args.output or root / "mechanism.png"
    render(load(input_path), output_path, args.profile_label)
    print(f"mechanism figure: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
