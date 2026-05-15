# PCB Assembly Puzzle

An interactive drag-and-drop educational tool for learning PCB assembly. Load an Altium Designer project (ZIP or CSV), the matching Gerber outline, and a STEP 3D model, then place each component onto its correct position on the rendered board.

## Features

- Loads Altium **Pick & Place** CSVs *and* Altium **PCB Object Report** CSVs (auto-detected from the header).
- Loads the project **BOM CSV** automatically when found next to the loaded file (or up one directory level), enriching the info panel with friendly part names, descriptions and manufacturer part numbers.
- Renders the **PCB top side from Gerber files** (copper, silkscreen, soldermask, drill) so the board view shows the real board image, not just an outline.
- Per-component **STEP 3D thumbnails**: the assembly is read through OCAF/XCAF, every designator is isolated, and each component is rendered top-down with its real colours. Thumbnails appear in the component list and on the board when a component is placed.
- Placed components show as their **STEP thumbnail** scaled to real mm size with the white render background alpha-keyed out, so they sit cleanly over the green PCB instead of as flat rectangles.
- **Component Information panel** with Designator, Category, BOM Name, BOM Description, Manufacturer Part Number, Size (W × H × 3D-height mm), and Position. Empty fields are omitted automatically.
- **Category filter** dropdown grouped by designator prefix (Resistors, Capacitors, ICs, Connectors, Test Points, Magnetorquer Pins, …) with per-category counts.
- Zoom / Pan / Fit-Board / Reset controls.
- Score tracking and a flashing red hint after three incorrect placements of the same component.

## Requirements

### Main app

- Python 3.10+
- PyQt5
- numpy
- pandas
- pcb-tools
- cairocffi (used by pcb-tools' Cairo backend for the board image)

```bash
pip install -r requirements.txt
```

### Optional — 3D component thumbnails

STEP rendering runs in a separate Python environment that has `pythonocc-core` installed (the wheel doesn't play well with the main app's dependencies). The easiest path is a conda env named `adcs-step`:

```bash
conda create -n adcs-step -c conda-forge pythonocc-core
```

The app auto-discovers `adcs-step` under common conda install roots (`miniconda3`, `anaconda3`, `miniforge3`, `mambaforge`, `.conda`). If your interpreter lives elsewhere, point at it explicitly:

```bash
export ADCS_STEP_PYTHON=/path/to/python   # interpreter with pythonocc-core
```

If no such environment is available, all other features still work — the **Load 3D Model** button simply reports the env is missing.

## Usage

```bash
python pcb_puzzle.py
```

1. **Load Altium ZIP or CSV** — pick the Altium project ZIP, an Object Report CSV, or a Pick & Place CSV. The matching `BOM*.csv` is auto-loaded if it sits in the same directory or one level above.
2. **Load Board Outline** — pick a Gerber ZIP (preferred — the full top side is rendered) or a single outline file (`.gm1` / `.gko` / `.gml` / `.gbr`).
3. **Load 3D Model (STEP)** — pick the project's STEP export. Per-component thumbnails render in ~15 s and populate the list and detail panel.
4. Drag a component from the list onto the board. Land it within the tolerance zone of its target to score; placement renders the STEP thumbnail at real mm size, rotation included.
5. After three incorrect attempts on the same component, a flashing red circle hints at the correct location.

## Project Structure

```
.
├── pcb_puzzle.py              # Main PyQt5 application
├── pcb_components.py          # ComponentItem fallback graphics item (used when no STEP thumb)
├── utils/
│   ├── parser.py              # PCBParser: CSV, BOM, Gerber outline + image, STEP orchestration
│   └── step_render_worker.py  # Standalone STEP -> per-component PNG worker (pythonocc-core)
├── downloads/                 # Example project files (not required)
├── requirements.txt
└── README.md
```

## License

MIT
