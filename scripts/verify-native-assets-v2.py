#!/usr/bin/env python3
"""V2 independently checks the catalog conversion and reviewed native backdrop.

uv run --with pillow==11.3.0 python scripts/verify-native-assets.py \
  --game .local/example/game --conversion .local/example/conversion
"""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import struct

from PIL import Image


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def verify(game, conversion):
    report=json.loads((conversion/"conversion.json").read_text())
    assert report["schema"]==2 and "native_background_repair" in report
    repair=report["native_background_repair"]
    assert repair["map"]=="HelixResearchPost"
    assert set(r["metatile"] for r in repair["metatiles"])=={0x223,0x298,0x289,0x28a}
    assert repair["source_refs"]==[0x6218]*4
    assert repair["source_metatile"]==0x248 and repair["source_layer"]==0
    for path,expected in report["overlay_files"].items():
        assert digest(conversion/"overlay"/path)==expected, f"Staged file changed: {path}"
        assert digest(game/path)==expected, f"Installed file changed: {path}"
    for path,expected in report["source_inputs"].items():
        if path not in report["overlay_files"]:
            assert digest(game/path)==expected, f"Unrelated input changed: {path}"
    for path,expected in report["evidence_files"].items():
        assert digest(conversion/"evidence"/path)==expected, f"Evidence changed: {path}"
    for folder in (conversion/"evidence").iterdir():
        if not folder.is_dir(): continue
        image=Image.open(folder/"native.png")
        raw=(folder/"native.4bpp").read_bytes()
        assert len(raw)==image.width*image.height//2
        # Decode native tiles independently; compare every index, not just hashes.
        for y in range(image.height):
            for x in range(image.width):
                tile=(y//8)*(image.width//8)+(x//8)
                value=raw[tile*32+(y%8)*4+(x%8)//2]
                value=(value>>4 if x%2 else value&15)
                assert value==image.getpixel((x,y)), f"4bpp pixel mismatch: {folder.name} ({x},{y})"
        colors=struct.unpack("<16H",(folder/"palette.gbapal").read_bytes())
        image_palette=image.getpalette()[:48]
        for i,color in enumerate(colors):
            assert tuple(image_palette[3*i:3*i+3])==tuple(((color>>s)&31)*8 for s in (0,5,10))
        assert image.info["transparency"]==0
    groups={
        "HelixResearchPost":("generic_building","helix_assets_post"),
        "HelixLaboratory":("lab","helix_assets_lab"),
    }
    summaries=[]
    for name,(source,clone) in groups.items():
        before=game/f"data/tilesets/secondary/{source}"; after=game/f"data/tilesets/secondary/{clone}"
        assets=[a for a in report["assets"] if a["map"]==name]
        allowed_metas={m for a in assets for row in a["metatiles"] for m in row}
        allowed_lower={v["metatile"] for v in repair["metatiles"]} if name=="HelixResearchPost" else set()
        allowed_tiles={t for a in assets for t in a["native_tile_indices"]}
        allowed_palettes={a["palette_slot"] for a in assets}
        assert (before/"metatile_attributes.bin").read_bytes()==(after/"metatile_attributes.bin").read_bytes()
        old=(before/"metatiles.bin").read_bytes(); new=(after/"metatiles.bin").read_bytes()
        assert len(old)==len(new)
        for i in range(len(old)//16):
            if i+512 in allowed_lower:
                assert new[i*16:i*16+8]==struct.pack("<4H",0x6218,0x6218,0x6218,0x6218), "Reviewed backdrop refs differ"
            else:
                assert old[i*16:i*16+8]==new[i*16:i*16+8], "Unapproved lower layer changed"
            if i+512 not in allowed_metas:
                assert old[i*16+8:i*16+16]==new[i*16+8:i*16+16], "Unrelated upper metatile changed"
        old_image=Image.open(before/"tiles.png"); new_image=Image.open(after/"tiles.png")
        assert old_image.size==new_image.size
        for y in range(old_image.height):
            for x in range(old_image.width):
                tile=512+(y//8)*(old_image.width//8)+x//8
                if tile not in allowed_tiles:
                    assert old_image.getpixel((x,y))==new_image.getpixel((x,y)), "Unrelated tile index changed"
        for slot in range(16):
            if slot not in allowed_palettes:
                assert (before/f"palettes/{slot:02}.pal").read_bytes()==(after/f"palettes/{slot:02}.pal").read_bytes()
        summaries.append({"map":name,"replaced_metatiles":len(allowed_metas),"reused_unreferenced_tiles":len(allowed_tiles),"new_palette_slots":sorted(allowed_palettes),"lower_layers_except_reviewed_backdrop_attributes_unrelated_tiles_and_palettes_preserved":True})
    original_post=(game/"data/layouts/HelixResearchPost/map.bin").read_bytes()
    post_cells=struct.unpack(f"<{len(original_post)//2}H",original_post)
    for row in repair["metatiles"]:
        assert row["positions"]==[[i%12,i//12] for i,value in enumerate(post_cells) if value&1023==row["metatile"]], "Backdrop cell accounting differs"
        assert row["lower_refs_after"]==[0x6218]*4
    assert repair["affected_map_cells"]==sum(len(v["positions"]) for v in repair["metatiles"])
    assert repair["affected_metatile_definitions"]==4
    source_floor=Image.open(game/"data/tilesets/secondary/generic_building/tiles.png")
    # Tile0x218 is the opaque peach field reused in each quadrant.
    assert all(source_floor.getpixel((24%16*8+x,24//16*8+y))!=0 for y in range(8) for x in range(8))
    original=game/"data/layouts/LittlerootTown_ProfessorBirchsLab"
    cloned=game/"data/layouts/HelixAssetsLaboratory"
    for filename in ("map.bin","border.bin"):
        assert (original/filename).read_bytes()==(cloned/filename).read_bytes()
    return {"schema":2,"native_background_repair_verified":True,"background_cells":repair["affected_map_cells"],"result":"passed-source-and-native-byte-assertions","conversion_sha256":digest(conversion/"conversion.json"),"verified_installed_files":len(report["overlay_files"]),"native_4bpp_and_RGB555_roundtrip":True,"lab_map_and_border_byte_identical":True,"maps":summaries,"runtime_acceptance":"separate exact-ROM mGBA evidence required"}


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game",type=Path,required=True)
    parser.add_argument("--conversion",type=Path,required=True)
    parser.add_argument("--output",type=Path)
    args=parser.parse_args(); result=verify(args.game,args.conversion)
    text=json.dumps(result,indent=2,sort_keys=True)+"\n"
    if args.output:
        assert not args.output.exists(), "Use a new audit receipt"
        args.output.write_text(text)
    print(text,end="")
