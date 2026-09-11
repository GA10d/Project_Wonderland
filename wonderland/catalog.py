from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
from pathlib import Path

from PIL import Image, ImageDraw

from .config import ROOT, STYLE
from .models import Asset


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Catalog:
    def __init__(self, root: Path = ROOT):
        self.root = root
        (root / "data").mkdir(exist_ok=True)
        self.db = sqlite3.connect(root / "data/assets.sqlite")
        self.db.execute("CREATE TABLE IF NOT EXISTS assets (id TEXT PRIMARY KEY, state TEXT, description TEXT, payload TEXT)")
        self.db.execute("CREATE TABLE IF NOT EXISTS inventory (path TEXT PRIMARY KEY, width INT, height INT, description TEXT)")
        self.db.commit()

    def close(self):
        self.db.close()

    def register(self, asset: Asset):
        if not (self.root / asset.image).is_file():
            raise ValueError(f"素材文件不存在：{asset.id}")
        self.db.execute("INSERT OR REPLACE INTO assets VALUES (?,?,?,?)", (
            asset.id, asset.state, " ".join([asset.name, *asset.tags]).lower(), asset.model_dump_json()))
        self.db.commit()

    def all(self) -> dict[str, Asset]:
        return {a.id: a for (payload,) in self.db.execute("SELECT payload FROM assets WHERE state='validated' ORDER BY id")
                for a in [Asset.model_validate_json(payload)]}

    def search(self, query: str, raw=False, limit=30):
        tokens = re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]+", query.lower())
        table, column = ("inventory", "description") if raw else ("assets", "description")
        where = " AND ".join(f"{column} LIKE ?" for _ in tokens) or "1"
        return self.db.execute(f"SELECT * FROM {table} WHERE {where} LIMIT ?",
                               [*(f"%{token}%" for token in tokens), limit]).fetchall()

    def brief(self):
        return [dict(id=a.id, name=a.name, category=a.category, tags=a.tags,
                     size_cells=[math.ceil(v / 32) for v in a.size])
                for a in self.all().values() if a.category not in ("character", "autotile")
                and (a.category != "tile" or a.provenance.get('kind') == 'openai_generated' or 'ground' in a.tags)]


def scan_inventory(catalog: Catalog, progress=print):
    """Index canonical 16px sources, not duplicate 32/48px or RPG Maker exports."""
    root = catalog.root
    sources = [
        root / "assets/raw/Modern_Farm_v1/16x16/Single_Files_16x16",
        root / "assets/raw/modernexteriors-win/Modern_Exteriors_16x16/Modern_Exteriors_Complete_Singles_16x16",
        root / "assets/raw/moderninteriors-win/1_Interiors/16x16/Theme_Sorter_Shadowless_Singles",
        root / "assets/raw/Modern_Office_Revamped_v1/4_Modern_Office_singles",
    ]
    rows = []
    for directory in sources:
        for path in sorted(directory.rglob("*.png")):
            if any(s in str(path) for s in ("32x32", "48x48", "Complete_Tileset_Singles")):
                continue
            with Image.open(path) as im:
                w, h = im.size
            relative = str(path.relative_to(root))
            rows.append((relative, w, h, relative.replace("_", " ").lower()))
    with catalog.db:
        catalog.db.execute("DELETE FROM inventory")
        catalog.db.executemany("INSERT INTO inventory VALUES (?,?,?,?)", rows)
    progress(f"已索引 {len(rows)} 个原始资源；尚未标注的资源不直接进入运行时。")
    return len(rows)


def normalized_mask(mask: int) -> int:
    for diagonal, a, b in ((16, 1, 2), (32, 2, 4), (64, 4, 8), (128, 8, 1)):
        if not (mask & a and mask & b):
            mask &= ~diagonal
    return mask


def build_autotile(source: Image.Image, offset: int, mask: int) -> Image.Image:
    """Compose four authored 8px quadrants into a 16px Blob tile.

    Atlas: 3x3 outer patch at (offset,0); concave 2x2 patch at (offset+3,0).
    Bits: N=1 E=2 S=4 W=8 NE=16 SE=32 SW=64 NW=128.
    """
    result = Image.new("RGBA", (16, 16))
    for qx, qy, horizontal, vertical, diagonal in (
        (0, 0, 8, 1, 128), (1, 0, 2, 1, 16),
        (0, 1, 8, 4, 64), (1, 1, 2, 4, 32),
    ):
        h, v, d = bool(mask & horizontal), bool(mask & vertical), bool(mask & diagonal)
        if h and v and not d:
            tx, ty = offset + (4 if qx == 0 else 3), (1 if qy == 0 else 0)
        else:
            tx = offset + (1 if h else 2 * qx)
            ty = 1 if v else 2 * qy
        x, y = tx * 16 + qx * 8, ty * 16 + qy * 8
        result.paste(source.crop((x, y, x + 8, y + 8)), (qx * 8, qy * 8))
    return result


def import_curated(catalog: Catalog, progress=print):
    root = catalog.root
    manifest = json.loads((root / "assets/manifests/limezu.json").read_text())
    out = root / "assets/normalized"
    out.mkdir(parents=True, exist_ok=True)
    for definition in manifest["definitions"]:
        path = root / "assets/raw" / definition["source"]
        if not path.exists():
            raise FileNotFoundError(f"缺少原始素材：{definition['source']}")
        with Image.open(path) as original:
            im = original.convert("RGBA")
        crop = definition.get("crop")
        if crop:
            x, y, w, h = crop
            im = im.crop((x, y, x + w, y + h))
        if definition.get('layers'):
            # Authored furniture prefabs: explicit source rectangles and local pixel offsets.
            im = Image.new('RGBA', tuple(definition['canvas']))
            for layer in definition['layers']:
                with Image.open(root / 'assets/raw' / layer['source']) as source:
                    x, y, w, h = layer['crop']
                    part = source.convert('RGBA').crop((x, y, x+w, y+h))
                im.alpha_composite(part, tuple(layer['at']))
        if definition.get("fill_from_pixel") is not None:
            # Solid background sampled from this pack's authored grass edge.
            im = Image.new("RGBA", (16, 16), im.getpixel(tuple(definition["fill_from_pixel"])))
        if not im.getbbox():
            raise ValueError(f"空白素材：{definition['id']}")
        im = im.resize((im.width * 2, im.height * 2), Image.Resampling.NEAREST)
        target = out / f"{definition['id']}.png"
        im.save(target)
        collision = definition.get("collision")
        catalog.register(Asset(
            id=definition["id"], name=definition["name"], category=definition["category"], tags=definition["tags"],
            source=str(path.relative_to(root)), image=str(target.relative_to(root)), size=im.size,
            anchor=tuple(v * 2 for v in definition["anchor"]),
            collision=tuple(v * 2 for v in collision) if collision else None,
            footprint=(max(1, math.ceil(collision[2] / 16)), max(1, math.ceil(collision[3] / 16))) if collision else (1, 1),
            door=tuple(v * 2 for v in definition["door"]) if definition.get("door") else None,
            sha256=digest(target), provenance={"author": "LimeZu", "manifest": "limezu.json", "crop": crop,
                                              "fill_from_pixel": definition.get("fill_from_pixel"),
                                              "layers": definition.get("layers"),
                                              "license": "local purchased pack; no standalone redistribution"},
        ))
    atlas_path = root / "assets/raw/Modern_Farm_v1/16x16/1_Terrains_16x16.png"
    with Image.open(atlas_path) as atlas:
        atlas = atlas.convert("RGBA")
        for kind, offset in (("path", 0), ("water", 16)):
            for mask in sorted({normalized_mask(m) for m in range(256)}):
                im = build_autotile(atlas, offset, mask).resize((32, 32), Image.Resampling.NEAREST)
                aid = f"auto.{kind}.{mask}"
                path = out / f"{aid}.png"
                im.save(path)
                catalog.register(Asset(id=aid, name=f"{kind} {mask}", category="autotile", tags=[kind],
                    source=str(atlas_path.relative_to(root)), image=str(path.relative_to(root)),
                    size=(32, 32), anchor=(0, 0), sha256=digest(path)))
    progress(f"已准备 {len(catalog.all())} 个已标注资源（含动画与 94 个边角图块）。")
    contact_sheet(catalog, root / "assets/previews/catalog.png")
    catalog.db.execute('CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT)')
    catalog.db.execute('INSERT OR REPLACE INTO metadata VALUES (?,?)', ('manifest_sha256', digest(root / 'assets/manifests/limezu.json')))
    catalog.db.commit()


def contact_sheet(catalog: Catalog, target: Path):
    assets = [a for a in catalog.all().values() if a.category not in ("tile", "autotile", "character")]
    sheet = Image.new("RGB", (1000, max(1, math.ceil(len(assets) / 5)) * 180), "#e3e8d7")
    draw = ImageDraw.Draw(sheet)
    for i, a in enumerate(assets):
        im = Image.open(catalog.root / a.image).convert("RGBA")
        im.thumbnail((184, 140), Image.Resampling.NEAREST)
        x, y = i % 5 * 200, i // 5 * 180
        sheet.paste(im, (x + (200 - im.width) // 2, y + 140 - im.height), im)
        draw.text((x + 8, y + 148), a.id, fill="#243e2e")
    target.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(target)


def ensure_catalog(root: Path = ROOT) -> Catalog:
    cat = Catalog(root)
    try:
        cat.db.execute('CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT)')
        revision = cat.db.execute("SELECT value FROM metadata WHERE key='manifest_sha256'").fetchone()
        manifest = root / 'assets/manifests/limezu.json'
        if not cat.all() or (manifest.exists() and revision != (digest(manifest),)):
            import_curated(cat)
    except BaseException:
        cat.close()
        raise
    return cat
