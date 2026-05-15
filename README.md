# PCB Assembly Puzzle

An interactive drag-and-drop educational tool for learning PCB assembly. Load an Altium Designer project ZIP, and place components onto their correct positions on the board outline.

## Features

- Loads Altium Pick & Place CSVs and Gerber board outlines from a ZIP
- Drag-and-drop components from a list onto the board view
- Score tracking for correct placements
- Visual hint system after repeated incorrect attempts
- Component information panel with designator, description, and target coordinates

🚀 Quick Start Guide
Step 1 — Install Miniconda

Download from docs.anaconda.com/miniconda. NOTE: install Miniconda, NOT Anaconda Distribution.
Run the installer with default options

Open the Anaconda prompt, go to the directory to load the git in.  Eg: /home/<user>/projects/

BASH
```
git clone https://github.com/Alfcon/APL.git

cd APL
```



## Requirements
- Python 3.6+
- PyQt5
- pandas
- gerber (python-gerber)

- Altium files
  - Altium project as a zip (ADCS Integration Board.zip)
  - Gerber file (Gerber for PCB1.PcbDoc.zip)
  - 3D Model (STEP) (STEP_[No Variations] for PCB1.PcbDoc.step)

## Installation

bash
```
conda create -n apl python=3.6.* -y

conda activate apl

pip install -r requirements.txt
```

## Usage

```bash
python pcb_puzzle.py
```

1. Click **Load Altium ZIP** and select a ZIP file containing Altium Pick & Place CSV and Gerber outline files.
2. Drag components from the list on the left onto the board.
3. Place each component within the tolerance zone of its target position to score points.
4. After 3 incorrect attempts on the same component, a flashing red circle hints at the correct location.

## Project Structure

```
├── pcb_puzzle.py          # Main application entry point
├── pcb_components.py      # ComponentItem graphics item class
├── utils/
│   └── parser.py          # PCBParser for CSV and Gerber file parsing
├── requirements.txt
└── README.md
```

## License

MIT
