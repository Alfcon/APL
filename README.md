# PCB Assembly Puzzle

An interactive drag-and-drop educational tool for learning PCB assembly. Load an Altium Designer project (ZIP or CSV), the matching Gerber outline, and a STEP 3D model, then place each component onto its correct position on the rendered board.

## Features

- Loads Altium **Pick & Place** CSVs *and* Altium **PCB Object Report** CSVs (auto-detected from the header).
- Loads the project **BOM CSV** automatically when found next to the loaded file (or up one directory level), enriching the info panel with friendly part names, descriptions and manufacturer part numbers.
- Renders the **PCB top side from Gerber files** (copper, silkscreen, soldermask, drill) so the board view shows the real board image, not just an outline.
- Per-component **STEP 3D thumbnails**: the assembly is read through OCAF/XCAF, every designator is isolated, and each component is rendered top-down with its real colours. Thumbnails appear in the component list and on the board when a component is placed.
- Placed components show as their **STEP thumbnail** scaled to real mm size with the white render background alpha-keyed out, so they sit cleanly over the green PCB instead of as flat rectangles.
- **Component Information panel** with Designator, Category, BOM Name, BOM Description, Manufacturer Part Number, Size (W × H × 3D-height mm), and Position. Empty fields are omitted automatically. A preview image of the selected component's STEP thumbnail is shown above the panel.
- **Category filter** dropdown grouped by designator prefix (Resistors, Capacitors, ICs, Connectors, Test Points, …) with per-category counts. The info panel's Category field additionally maps designators that don't follow the alpha-prefix convention (`X+`, `Y-`, `+3V3`, `VBUS1`, …) to their real category (Magnetorquer Pins, Test Points).
- **Hint button** — select a component in the list and press *Hint: Show Selected Position* to center the view on its target and flash a red circle there.
- Zoom (buttons or mouse wheel, anchored under the cursor) / Fit-Board / Reset controls.
- Score tracking: +1 per correct placement; from the third incorrect attempt on the same component onward, each miss costs a point and the correct location flashes automatically.
- Components without a STEP thumbnail (or when no STEP model is loaded) are placed as green rectangles, rotated to the component's rotation — footprint-sized when loaded from an Object Report CSV, a default 3 × 2 mm otherwise.

## Requirements

- Python 3.10+
- PyQt5
- numpy
- pandas
- pcb-tools
- cairocffi (used by pcb-tools' Cairo backend for the board image)

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/Alfcon/APL.git
cd APL
```

### 2. Install the main app

A virtual environment is recommended:

```bash
python3 -m venv apl      # Windows: python -m venv apl
source apl/bin/activate   # Windows: apl\Scripts\activate
pip install -r requirements.txt
```

> **Note:** `cairocffi` needs the native Cairo library. On Debian/Ubuntu:
> `sudo apt install libcairo2`; on Fedora: `sudo dnf install cairo`;
> on macOS: `brew install cairo`.
>
> On Debian/Ubuntu, if `python3 -m venv` fails with an `ensurepip` error,
> install the venv module first: `sudo apt install python3-venv`.

### 3. Optional — 3D component thumbnails

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
5. Stuck? Select the component and press **Hint: Show Selected Position**, or fail three times on it — either way a flashing red circle marks the correct location (from the third miss onward, each miss also costs a point).
6. **Reset** clears all placements and restores the full component list.

## Project Structure

```
.
├── pcb_puzzle.py              # Main PyQt5 application
├── pcb_components.py          # ComponentItem fallback graphics item (used when no STEP thumb)
├── utils/
│   ├── parser.py              # PCBParser: CSV, BOM, Gerber outline + image, STEP orchestration
│   └── step_render_worker.py  # Standalone STEP -> per-component PNG worker (pythonocc-core)
├── downloads/                 # Project files from Altium
├── requirements.txt
└── README.md
```

## License

MIT
