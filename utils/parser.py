import zipfile
import os
import re
import json
import glob
import subprocess
import tempfile
import pandas as pd
import gerber
import gerber.common

OUTLINE_EXTS = ('.gm1', '.gko', '.gml')

_STEP_WORKER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'step_render_worker.py')


def find_step_render_python():
    """Locate a Python interpreter with pythonocc-core for STEP rendering.

    Order: ADCS_STEP_PYTHON env var, then a conda env named 'adcs-step' under
    common conda install roots. Returns the interpreter path or None.
    """
    env_override = os.environ.get('ADCS_STEP_PYTHON')
    if env_override and os.path.exists(env_override):
        return env_override

    home = os.path.expanduser('~')
    roots = ['miniconda3', 'anaconda3', 'miniforge3', 'mambaforge', '.conda']
    for root in roots:
        candidate = os.path.join(home, root, 'envs', 'adcs-step', 'bin', 'python')
        if os.path.exists(candidate):
            return candidate

    # Fall back to a glob in case of a non-standard layout.
    for hit in glob.glob(os.path.join(home, '*', 'envs', 'adcs-step', 'bin', 'python')):
        return hit
    return None

_CHIP_RE = re.compile(r'^(?:RESC|CAPC|INDC|LEDC|FBC|VARC|FUSC)(\d{2})(\d{2})', re.IGNORECASE)
_TP_RE = re.compile(r'test[_-]?point[_-]?(\d+(?:\.\d+)?)mm', re.IGNORECASE)


def estimate_footprint_size(footprint, default=(3.0, 2.0)):
    """Return (width_mm, height_mm) inferred from an IPC-7351-ish footprint name."""
    if not footprint:
        return default
    m = _CHIP_RE.match(footprint)
    if m:
        return (int(m.group(1)) / 10.0, int(m.group(2)) / 10.0)
    m = _TP_RE.search(footprint)
    if m:
        d = float(m.group(1))
        return (d, d)
    return default

class PCBParser:
    def __init__(self):
        self.temp_dir = tempfile.mkdtemp()
        self.components = []
        self.board_outline = []  # list of ((x1_mm, y1_mm), (x2_mm, y2_mm)) line segments
        self.board_image_path = None
        self.board_image_bbox_mm = None  # (min_x, min_y, max_x, max_y) in mm
        self.step_thumbnails = {}  # designator -> per-component PNG path
        self.step_thumb_bounds = {}  # designator -> (xmin, ymin, xmax, ymax) mm region of the PNG
        self.step_thumb_heights = {}  # designator -> z extent (mm) from the STEP bbox
        self.bom_by_designator = {}  # designator -> {'name','description','part_number'}

    def extract_zip(self, zip_path):
        try:
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(self.temp_dir)
            return True
        except Exception as e:
            print(f"Error extracting ZIP: {e}")
            return False

    def parse_files(self):
        self.components = []
        self.board_outline = []

        csv_file = None
        outline_candidates = []

        for root, dirs, files in os.walk(self.temp_dir):
            for file in files:
                lower_file = file.lower()
                full_path = os.path.join(root, file)

                if lower_file.endswith('.csv'):
                    is_pnp_name = "pick" in lower_file and "place" in lower_file
                    if is_pnp_name or csv_file is None:
                        csv_file = full_path

                if lower_file.endswith(OUTLINE_EXTS):
                    outline_candidates.append(full_path)
                elif "profile" in lower_file and lower_file.endswith('.gbr'):
                    outline_candidates.append(full_path)

        if csv_file:
            self._parse_csv(csv_file)
        else:
            print("Warning: Could not find a component CSV file.")

        if outline_candidates:
            self._parse_outline_candidates(outline_candidates)
        else:
            print("Warning: Could not find Gerber board outline file.")

        return len(self.components) > 0

    def load_outline_from_dir(self, dir_path):
        """Scan a directory tree for outline files and parse the best candidate."""
        self.board_outline = []
        candidates = []
        for root, dirs, files in os.walk(dir_path):
            for file in files:
                lower = file.lower()
                full = os.path.join(root, file)
                if lower.endswith(OUTLINE_EXTS):
                    candidates.append(full)
                elif "profile" in lower and lower.endswith('.gbr'):
                    candidates.append(full)
        if not candidates:
            print("Warning: no outline file found in directory.")
            return False
        self._parse_outline_candidates(candidates)
        return bool(self.board_outline)

    def load_outline_zip(self, zip_path):
        """Extract a Gerber ZIP into temp_dir, parse the outline, and render the board image."""
        if not self.extract_zip(zip_path):
            return False
        ok = self.load_outline_from_dir(self.temp_dir)
        if ok:
            self.render_board_image(self.temp_dir)
        return ok

    def render_board_image(self, gerber_dir, dpi=500):
        """Render the top side of the PCB from a directory of Gerber files. Best-effort."""
        self.board_image_path = None
        self.board_image_bbox_mm = None

        try:
            import gerber.common as _common
            import gerber.pcb as _pcb_mod
            from gerber.pcb import PCB
            from gerber.render.cairo_backend import GerberCairoContext
        except Exception as e:
            print(f"Board render skipped (imports failed): {e}")
            return False

        # pcb-tools' gerber.common.read uses the removed 'rU' file mode on Python 3.11+.
        # Patch it (and gerber.pcb's bound reference) for the duration of this call.
        def _patched_read(filename):
            with open(filename, 'r', encoding='utf-8', errors='ignore') as f:
                data = f.read()
            return _common.loads(data, filename)

        orig_common = _common.read
        orig_pcb = _pcb_mod.gerber_read
        _common.read = _patched_read
        _pcb_mod.gerber_read = _patched_read

        try:
            pcb = PCB.from_directory(gerber_dir)
            if not pcb.layers:
                return False

            outline = next((l for l in pcb.layers if l.layer_class == 'outline'), None)
            if outline is None or not list(outline.primitives):
                # Common Altium case: GKO is empty, real outline lives on GM1.
                for root, _dirs, files in os.walk(gerber_dir):
                    for f in files:
                        if f.lower().endswith('.gm1'):
                            gm1 = _patched_read(os.path.join(root, f))
                            gm1.layer_class = 'outline'
                            pcb.layers = [gm1 if l.layer_class == 'outline' else l
                                          for l in pcb.layers]
                            outline = gm1
                            break
                    if outline is not None and list(outline.primitives):
                        break

            if outline is None or not list(outline.primitives):
                print("Board render skipped (no usable outline).")
                return False

            # Anchor every rendered layer to the outline bounds so the PNG extent
            # matches the outline (not whichever layer happens to be rendered first).
            outline_bounds = getattr(outline, 'bounds', None) or outline.bounding_box

            ctx = GerberCairoContext(scale=dpi)
            for layer in pcb.top_layers:
                ctx.render_layer(layer, bounds=outline_bounds)

            (min_x, max_x), (min_y, max_y) = outline_bounds
            unit_scale = 25.4 if (outline.units or '').lower() in ('inch', 'in', 'inches') else 1.0
            bbox_mm = (min_x * unit_scale, min_y * unit_scale,
                       max_x * unit_scale, max_y * unit_scale)

            out_path = os.path.join(gerber_dir, '_board_top.png')
            ctx.dump(out_path)

            self.board_image_path = out_path
            self.board_image_bbox_mm = bbox_mm
            print(f"Rendered board image: {out_path}  bbox_mm={bbox_mm}")
            return True
        except Exception as e:
            print(f"Board render failed: {e}")
            return False
        finally:
            _common.read = orig_common
            _pcb_mod.gerber_read = orig_pcb

    def load_outline_file(self, filepath):
        """Parse a single Gerber file as the outline."""
        self.board_outline = []
        self._parse_outline_candidates([filepath])
        return bool(self.board_outline)

    def render_step_image(self, step_path, components, tile_px=512):
        """Render per-component thumbnails from a STEP file via the pythonocc sidecar env.

        Each component in `components` (dicts with designator/x/y/width_mm/height_mm)
        gets its own tightly-framed top-down PNG. On success populates
        self.step_thumbnails (designator -> png path) and self.step_thumb_bounds
        (designator -> mm region) and returns True. Returns False (with a printed
        reason) on any failure.
        """
        self.step_thumbnails = {}
        self.step_thumb_bounds = {}
        self.step_thumb_heights = {}

        if not os.path.exists(step_path):
            print(f"STEP render skipped: file not found: {step_path}")
            return False
        if not components:
            print("STEP render skipped: no components to render.")
            return False

        step_python = find_step_render_python()
        if not step_python:
            print("STEP render skipped: no pythonocc env found "
                  "(expected conda env 'adcs-step' or $ADCS_STEP_PYTHON).")
            return False
        if not os.path.exists(_STEP_WORKER):
            print(f"STEP render skipped: worker script missing: {_STEP_WORKER}")
            return False

        out_dir = os.path.join(self.temp_dir, '_step_thumbs')
        components_json = os.path.join(self.temp_dir, '_step_components.json')
        payload = [{
            'designator': c['designator'],
            'x': c['x'],
            'y': c['y'],
            'width_mm': c.get('width_mm', 3.0),
            'height_mm': c.get('height_mm', 2.0),
        } for c in components]
        with open(components_json, 'w') as f:
            json.dump(payload, f)

        try:
            proc = subprocess.run(
                [step_python, _STEP_WORKER, step_path, out_dir,
                 components_json, str(tile_px)],
                capture_output=True, text=True, timeout=600,
            )
        except subprocess.TimeoutExpired:
            print("STEP render failed: timed out.")
            return False

        if proc.returncode != 0:
            print(f"STEP render failed (exit {proc.returncode}): "
                  f"{proc.stderr.strip()[-500:]}")
            return False

        json_line = None
        for line in proc.stdout.splitlines():
            line = line.strip()
            if line.startswith('{') and line.endswith('}'):
                json_line = line
        if not json_line:
            print(f"STEP render failed: no JSON result. stderr: {proc.stderr.strip()[-300:]}")
            return False

        try:
            info = json.loads(json_line)
            thumbs = info['thumbs']
        except (ValueError, KeyError) as e:
            print(f"STEP render failed: bad result JSON: {e}")
            return False

        if not thumbs:
            print("STEP render failed: no component thumbnails produced.")
            return False

        self.step_thumbnails = thumbs
        self.step_thumb_bounds = {
            d: tuple(b) for d, b in info.get('bounds', {}).items()
        }
        self.step_thumb_heights = {
            d: float(h) for d, h in info.get('heights', {}).items()
        }
        print(f"Rendered {len(thumbs)} STEP component thumbnails into {out_dir}")
        return True

    def parse_file(self, filepath):
        """Parse a standalone CSV file (no ZIP extraction)."""
        self.components = []
        self._parse_csv(filepath)
        return len(self.components) > 0

    def _parse_csv(self, filepath):
        """Sniff the CSV header and dispatch to the right parser."""
        try:
            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                head = f.read(4096)
        except Exception as e:
            print(f"Error reading CSV header: {e}")
            return

        if 'Object Kind' in head:
            self._parse_object_report(filepath)
        else:
            self._parse_pnp(filepath)

    @staticmethod
    def _build_pad_bboxes(df):
        """For each Component designator, return (min_x, min_y, max_x, max_y) of its pads in mm.
        Accounts for per-pad rotation: X/Y Size are in the pad's local frame, so 90/270 rotated
        pads have width and height swapped in world coordinates.
        """
        bboxes = {}
        if 'Object Kind' not in df.columns:
            return bboxes
        pads = df[df['Object Kind'].astype(str).str.strip() == 'Pad']
        sx_col = 'X Size (All Layers) (mm)'
        sy_col = 'Y Size (All Layers) (mm)'
        required = ['Component', 'X1 (mm)', 'Y1 (mm)', sx_col, sy_col]
        if any(c not in pads.columns for c in required) or pads.empty:
            return bboxes

        for name, group in pads.groupby(pads['Component'].astype(str).str.strip()):
            xs_min, xs_max, ys_min, ys_max = [], [], [], []
            for _, prow in group.iterrows():
                try:
                    cx = float(prow['X1 (mm)'])
                    cy = float(prow['Y1 (mm)'])
                    sx = max(float(prow[sx_col]), 0.0)
                    sy = max(float(prow[sy_col]), 0.0)
                except (ValueError, TypeError):
                    continue
                pad_rot = 0.0
                if 'Rotation' in prow.index:
                    try:
                        pad_rot = float(str(prow['Rotation']).replace('deg', '').strip())
                    except (ValueError, TypeError):
                        pad_rot = 0.0
                if int(round(pad_rot)) % 180 == 90:
                    sx, sy = sy, sx
                xs_min.append(cx - sx / 2)
                xs_max.append(cx + sx / 2)
                ys_min.append(cy - sy / 2)
                ys_max.append(cy + sy / 2)
            if xs_min:
                bboxes[name] = (min(xs_min), min(ys_min), max(xs_max), max(ys_max))
        return bboxes

    def _parse_object_report(self, filepath):
        """Parse an Altium PCB Object Report CSV (filters Object Kind == 'Component')."""
        self.bom_by_designator = {}
        try:
            df = pd.read_csv(filepath, low_memory=False)
        except Exception as e:
            print(f"Error reading Object Report CSV: {e}")
            return

        if 'Object Kind' not in df.columns:
            print("Error: Object Report CSV missing 'Object Kind' column.")
            return

        pad_bboxes = self._build_pad_bboxes(df)

        comp = df[df['Object Kind'].astype(str).str.strip() == 'Component']

        if 'Layer' in comp.columns:
            comp = comp[~comp['Layer'].astype(str).str.lower().str.contains('bottom', na=False)]

        required = ['Designator', 'X1 (mm)', 'Y1 (mm)']
        missing = [c for c in required if c not in comp.columns]
        if missing:
            print(f"Error: Object Report missing required columns: {missing}")
            return

        for _, row in comp.iterrows():
            designator = str(row['Designator']).strip()
            if not designator or designator.lower() == 'nan':
                continue

            try:
                x = float(str(row['X1 (mm)']).replace('mm', '').strip())
                y = float(str(row['Y1 (mm)']).replace('mm', '').strip())
            except (ValueError, TypeError):
                continue

            description = ''
            if 'Component Comment' in comp.columns:
                description = str(row['Component Comment']).strip()
            if (not description or description.lower() == 'nan') and 'Footprint' in comp.columns:
                description = str(row['Footprint']).strip()
            if not description or description.lower() == 'nan':
                description = "Unknown Component"

            rotation = 0.0
            if 'Rotation' in comp.columns:
                rot_str = str(row['Rotation']).replace('deg', '').strip()
                try:
                    rotation = float(rot_str)
                except (ValueError, TypeError):
                    rotation = 0.0

            footprint = ''
            if 'Footprint' in comp.columns:
                footprint = str(row['Footprint']).strip()
                if footprint.lower() == 'nan':
                    footprint = ''

            width_mm = None
            height_mm = None
            bbox = pad_bboxes.get(designator)
            if bbox:
                world_w = bbox[2] - bbox[0]
                world_h = bbox[3] - bbox[1]
                margin = 0.2  # mm
                if int(round(rotation)) % 180 == 90:
                    width_mm = world_h + 2 * margin
                    height_mm = world_w + 2 * margin
                else:
                    width_mm = world_w + 2 * margin
                    height_mm = world_h + 2 * margin
            if not width_mm or not height_mm or width_mm <= 0 or height_mm <= 0:
                width_mm, height_mm = estimate_footprint_size(footprint)

            self.components.append({
                'designator': designator,
                'x': x,
                'y': y,
                'description': description,
                'rotation': rotation,
                'footprint': footprint,
                'width_mm': width_mm,
                'height_mm': height_mm,
            })

        print(f"Successfully parsed {len(self.components)} components from Object Report.")

        # Pick up a sibling BOM CSV if one exists in the same directory tree.
        # (When loading from a ZIP this looks inside the temp dir; the caller
        # is expected to also call find_and_load_bom on the ZIP's source dir.)
        self.find_and_load_bom(os.path.dirname(os.path.abspath(filepath)))

    def find_and_load_bom(self, start_dir):
        """Look in start_dir's tree (and its parent's tree) for a CSV whose name
        contains 'BOM'. Loads the first one whose columns look like a BOM."""
        seen = set()
        for d in (start_dir, os.path.dirname(start_dir or '') or None):
            if not d or d in seen or not os.path.isdir(d):
                continue
            seen.add(d)
            for root, _dirs, files in os.walk(d):
                for f in files:
                    if not f.lower().endswith('.csv') or 'bom' not in f.lower():
                        continue
                    if self._parse_bom_csv(os.path.join(root, f)):
                        return

    def _parse_bom_csv(self, path):
        """Populate self.bom_by_designator from a BOM CSV. Returns True on success."""
        try:
            df = pd.read_csv(path, low_memory=False)
        except Exception as e:
            print(f"BOM read failed for {path}: {e}")
            return False
        cols = {c.lower(): c for c in df.columns}
        designator_col = cols.get('designator')
        if not designator_col:
            return False
        name_col = cols.get('name')
        desc_col = cols.get('description')
        pn_col = cols.get('part number') or cols.get('manufacturer part number')

        count = 0
        for _, row in df.iterrows():
            def _cell(col):
                if not col or col not in row.index:
                    return ''
                v = row[col]
                if pd.isna(v):
                    return ''
                return str(v).strip().rstrip(',').strip()
            info = {
                'name': _cell(name_col),
                'description': _cell(desc_col),
                'part_number': _cell(pn_col),
            }
            for d in str(row[designator_col]).split(','):
                d = d.strip()
                if d and d.lower() != 'nan':
                    self.bom_by_designator[d] = info
                    count += 1
        print(f"Loaded BOM: {count} designators from {os.path.basename(path)}")
        return True

    def _parse_pnp(self, filepath):
        try:
            with open(filepath, 'r') as f:
                lines = f.readlines()

            header_idx = 0
            for i, line in enumerate(lines[:20]):
                 if "Designator" in line or "RefDes" in line:
                     header_idx = i
                     break

            df = pd.read_csv(filepath, skiprows=header_idx)
            df.columns = [col.strip().lower() for col in df.columns]

            for index, row in df.iterrows():
                 designator_col = next((col for col in df.columns if 'designator' in col or 'refdes' in col), None)
                 x_col = next((col for col in df.columns if 'mid x' in col or 'center-x' in col or 'x (mm)' in col), None)
                 y_col = next((col for col in df.columns if 'mid y' in col or 'center-y' in col or 'y (mm)' in col), None)
                 desc_col = next((col for col in df.columns if 'comment' in col or 'description' in col or 'value' in col), None)
                 layer_col = next((col for col in df.columns if 'layer' in col or 'side' in col), None)

                 if not all([designator_col, x_col, y_col]):
                     continue

                 if layer_col and 'bottom' in str(row[layer_col]).lower():
                     continue

                 designator = str(row[designator_col]).strip()
                 if not designator or designator == 'nan':
                     continue

                 try:
                     x_str = str(row[x_col]).replace('mm', '').replace('mil', '').strip()
                     y_str = str(row[y_col]).replace('mm', '').replace('mil', '').strip()
                     x = float(x_str)
                     y = float(y_str)
                 except ValueError:
                     continue

                 description = str(row[desc_col]).strip() if desc_col else "No description available"
                 if description == 'nan':
                     description = "Unknown Component"

                 self.components.append({
                     'designator': designator,
                     'x': x,
                     'y': y,
                     'description': description
                 })

            print(f"Successfully parsed {len(self.components)} components.")

        except Exception as e:
            print(f"Error parsing Pick and Place file: {e}")

    def _parse_outline_candidates(self, candidates):
        """Try candidates in priority order; keep the first one with primitives."""
        priority = {'.gm1': 0, '.gko': 1, '.gml': 2, '.gbr': 3}
        ordered = sorted(candidates, key=lambda p: priority.get(os.path.splitext(p)[1].lower(), 9))
        for path in ordered:
            segments = self._read_outline_segments(path)
            if segments:
                self.board_outline = segments
                print(f"Successfully parsed {len(segments)} outline segments from {os.path.basename(path)}.")
                return
        print("Warning: outline files found but none contained drawable primitives.")

    def _read_outline_segments(self, filepath):
        """Read a Gerber file and return its Line primitives as mm segments."""
        try:
            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                data = f.read()
            g = gerber.common.loads(data, filepath)
        except Exception as e:
            print(f"Error parsing {os.path.basename(filepath)}: {e}")
            return []

        if g is None:
            return []

        units = (getattr(g, 'units', 'metric') or 'metric').lower()
        scale = 25.4 if units in ('inch', 'in', 'inches') else 1.0

        segments = []
        for p in getattr(g, 'primitives', []):
            start = getattr(p, 'start', None)
            end = getattr(p, 'end', None)
            if start is None or end is None:
                continue
            segments.append((
                (start[0] * scale, start[1] * scale),
                (end[0] * scale, end[1] * scale),
            ))
        return segments
