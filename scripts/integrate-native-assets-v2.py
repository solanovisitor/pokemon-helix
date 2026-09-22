#!/usr/bin/env python3
"""Successor V2: four pinned assets and the requested cohesive post backdrop.

Run with uv run --with pillow==11.3.0. No image generation or inference occurs.
The provider images are immutable inputs. Every derivative has its own hash.
"""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import struct
import urllib.request

from PIL import Image, ImageDraw

REVISION = "d7c825f2d15b0818d549b8367d1054cb53c23713"
DATASET = "todeschini/helix-assets"
SELECTION = [
    dict(asset="post_modular_furniture", variation="chalk_sage", image="5799eb6b628bca9bb0be72cf238fb7045336d439b00a45a99c44d76d43b67da8", map="HelixResearchPost", secondary="generic_building", clone="helix_assets_post", symbol="HelixAssetsPost", x=2, y=5, metas=[[0x248,0x249],[0x250,0x251]], bounds=[2,0,30,32]),
    dict(asset="lab_registration_terminal", variation="mineral_silver", image="7b55a683086d993f1ed805605afcc7badc73a3c62ccef67764b93ee96371a53b", map="HelixLaboratory", secondary="lab", clone="helix_assets_lab", symbol="HelixAssetsLab", x=3, y=0, metas=[[0x212,0x213],[0x21a,0x21b]], bounds=[0,10,32,32]),
    dict(asset="lab_preparation_terminal", variation="mineral_silver", image="970bc44f1cb767d639c610b48c28012b08e2158e5903ac20e305898a3897be27", map="HelixLaboratory", secondary="lab", clone="helix_assets_lab", symbol="HelixAssetsLab", x=1, y=9, metas=[[0x230],[0x238]], bounds=[0,1,16,32]),
    dict(asset="indoor_potted_tree", variation="2026-v12", id="wave12-indoor-potted-tree-2026-v12", image="ba35dd2fb6f3ee8a0d1da82134fb5a42c9c0ff35f0832413c84c0aba47ff1449", map="HelixResearchPost", secondary="generic_building", clone="helix_assets_post", symbol="HelixAssetsPost", x=8, y=1, positions=[[8,1],[9,1]], metas=[[0x290],[0x298]], bounds=[0,1,16,32]),
]


def digest(data):
    return sha256(data).hexdigest()


def encoded(image, *, indexed=False):
    out = BytesIO()
    image.save(out, "PNG", **({"bits": 4, "transparency": 0} if indexed else {}))
    return out.getvalue()


def palette(raw):
    lines = raw.decode().splitlines()
    assert lines[:3] == ["JASC-PAL", "0100", "16"]
    return [tuple(map(int, line.split())) for line in lines[3:19]]


def palette_bytes(colors):
    return ("JASC-PAL\n0100\n16\n" + "\n".join(" ".join(map(str, c)) for c in colors) + "\n").encode()


def context(game, secondary, overlay=None):
    overlay = overlay or {}
    def read(path):
        return overlay[path] if path in overlay else (game/path).read_bytes()
    roots = ["data/tilesets/primary/building", f"data/tilesets/secondary/{secondary}"]
    return {
        "sheets": [Image.open(BytesIO(read(f"{p}/tiles.png"))).copy() for p in roots],
        "metas": [read(f"{p}/metatiles.bin") for p in roots],
        "palettes": {i: palette(read(f"{roots[int(i>=6)]}/palettes/{i:02}.pal")) for i in range(13)},
    }


def render(c, metas, layers=(0,1)):
    image = Image.new("RGBA", (len(metas[0])*16, len(metas)*16))
    for my,row in enumerate(metas):
        for mx,meta in enumerate(row):
            refs=struct.unpack_from("<8H", c["metas"][int(meta>=512)], meta%512*16)
            for layer in layers:
                for part,ref in enumerate(refs[layer*4:layer*4+4]):
                    tile=ref&1023; sheet=c["sheets"][int(tile>=512)]; tile%=512
                    for y in range(8):
                        for x in range(8):
                            color=sheet.getpixel((tile%16*8+(7-x if ref&1024 else x),tile//16*8+(7-y if ref&2048 else y)))
                            if color:
                                image.putpixel((mx*16+part%2*8+x,my*16+part//2*8+y),(*c["palettes"][ref>>12][color],255))
    return image


def map_grid(raw,width,height):
    cells=struct.unpack(f"<{width*height}H",raw)
    return [[cells[y*width+x]&1023 for x in range(width)] for y in range(height)]


def native_image(source, spec):
    """One exact uniform affine scale, bottom/center anchor, no visible crop."""
    rgba=Image.open(BytesIO(source)).convert("RGBA")
    bbox=rgba.getchannel("A").point(lambda v:255 if v>=4 else 0).getbbox()
    assert bbox is not None
    x0,y0,x1,y1=spec.get("fit_bounds",spec["bounds"])
    scale=min((x1-x0)/(bbox[2]-bbox[0]),(y1-y0)/(bbox[3]-bbox[1]))
    left=(x0+x1-(bbox[2]-bbox[0])*scale)/2
    top=y1-(bbox[3]-bbox[1])*scale
    size=(len(spec["metas"][0])*16,len(spec["metas"])*16)
    matrix=(1/scale,0,bbox[0]-left/scale,0,1/scale,bbox[1]-top/scale)
    sampled=rgba.transform(size,Image.Transform.AFFINE,matrix,Image.Resampling.NEAREST)
    counts=Counter(tuple(v>>3 for v in p[:3]) for p in sampled.getdata() if p[3]>=128)
    ranked=sorted(counts,key=lambda c:(-counts[c],c))
    assert ranked
    chosen=ranked[:1]
    while len(chosen)<min(15,len(ranked)):
        def score(c):
            dist=min(sum((a-b)**2 for a,b in zip(c,v)) for v in chosen)
            return (dist*dist*counts[c],counts[c],c)
        chosen.append(max((c for c in ranked if c not in chosen),key=score))
    colors=[(0,0,0)]+[tuple(v<<3 for v in c) for c in chosen]+[(0,0,0)]*(15-len(chosen))
    native=Image.new("P",size); native.putpalette([v for c in colors for v in c]+[0]*720)
    indices=[]
    for p in sampled.getdata():
        value=tuple(v>>3 for v in p[:3])
        indices.append(0 if p[3]<128 else 1+min(range(len(chosen)),key=lambda i:sum((a-b)**2 for a,b in zip(value,chosen[i]))))
    native.putdata(indices); native.info["transparency"]=0
    return native,colors,{"source_size":list(rgba.size),"source_alpha_bounds":list(bbox),"registration_alpha_threshold":4,"nonzero_alpha_bounds":rgba.getchannel("A").getbbox(),"alpha_1_to_3_pixels_excluded_from_registration":sum(rgba.getchannel("A").histogram()[1:4]),"alpha_1_to_127_pixels_excluded_from_native_opacity":sum(rgba.getchannel("A").histogram()[1:128]),"original_foreground_bounds":spec["bounds"],"target_foreground_bounds":spec.get("fit_bounds",spec["bounds"]),"uniform_scale":scale,"affine_output_to_input":matrix,"anchor":"bottom_center_of_original_foreground","alpha_threshold":128,"resampling":"nearest","palette_recipe":"deterministic occurrence-weighted RGB555 separation; 15 colors plus transparent zero","visible_source_crop":False,"native_alpha_bounds":native.convert("RGBA").getbbox()}


def tile_bytes(image):
    return bytes(image.getpixel((tx+x,ty+y)) | image.getpixel((tx+x+1,ty+y))<<4 for ty in range(0,image.height,8) for tx in range(0,image.width,8) for y in range(8) for x in range(0,8,2))


def integrate(game, catalog, output, install, table_variation):
    game=game.resolve(); output=output.resolve()
    assert not output.exists(), "Use a fresh output directory; conversion evidence is immutable"
    assert game.name=="game" and ("artifacts" in game.parts or ".local" in game.parts), "Use an isolated artifacts/.local game checkout"
    overlay={}; evidence={}; before={}; generated={}; maps={}; report={"schema":2,"successor_of":"integrate-native-assets.py; V1 retained as rejected visual diagnostic","requested_revision":"Cohesive native post backdrop and full-footprint table; no generated-art changes","dataset":DATASET,"config":"gallery","revision":REVISION,"converter_sha256":digest(Path(__file__).read_bytes()),"source_art_modified":False,"paid_calls":0,"assets":[],"runtime_acceptance":"pending exact-ROM mGBA review"}
    def read(path):
        raw=(game/path).read_bytes(); before[path]=digest(raw); return raw
    layouts=json.loads(read("data/layouts/layouts.json"))
    selection=deepcopy(SELECTION)
    table=selection[0]
    table.update(variation=table_variation,fit_bounds=[0,0,32,32],image={"chalk_sage":"5799eb6b628bca9bb0be72cf238fb7045336d439b00a45a99c44d76d43b67da8","slate_cobalt":"ba827c5938b7180ca0f70f910e12ff2582da76bb8837b3fdcf61f90e44be2f2f"}[table_variation])
    for spec in selection:
        name=spec["map"]
        if name not in maps:
            header_path=f"data/maps/{name}/map.json"; header=json.loads(read(header_path))
            layout=next(v for v in layouts["layouts"] if v["id"]==header["layout"])
            assert layout["secondary_tileset"]==("gTileset_Lab" if name=="HelixLaboratory" else "gTileset_GenericBuilding")
            raw=read(layout["blockdata_filepath"]); border=read(layout["border_filepath"])
            for group in ("object_events","bg_events","coord_events","warp_events"):
                assert group in header
            original=context(game,spec["secondary"])
            grid=map_grid(raw,layout["width"],layout["height"])
            evidence[f"{name}-before.png"]=encoded(render(original,grid))
            roots=["data/tilesets/primary/building",f'data/tilesets/secondary/{spec["secondary"]}']
            for folder in roots:
                for filename in ["tiles.png","metatiles.bin","metatile_attributes.bin"]+[f"palettes/{i:02}.pal" for i in range(16)]:
                    read(f"{folder}/{filename}")
            meta_ids=set(v&1023 for v in struct.unpack(f"<{len(raw)//2}H",raw)+struct.unpack(f"<{len(border)//2}H",border))
            refs=[r for m in meta_ids for r in struct.unpack_from("<8H",original["metas"][int(m>=512)],m%512*16)]
            used_tiles={r&1023 for r in refs}; used_palettes={r>>12 for r in refs}
            available=[i for i in range(768,1012) if i not in used_tiles]
            available_palettes=[i for i in range(6,13) if i not in used_palettes]
            assert available_palettes, "No free scene palette"
            clone_root=f'data/tilesets/secondary/{spec["clone"]}'
            assert not (game/clone_root).exists(), "Already installed"
            for filename in ["tiles.png","metatiles.bin","metatile_attributes.bin"]+[f"palettes/{i:02}.pal" for i in range(16)]:
                overlay[f"{clone_root}/{filename}"]=(game/roots[1]/filename).read_bytes()
            maps[name]=dict(header=header,layout=layout,raw=raw,grid=grid,context=original,clone_root=clone_root,available=available,palettes=available_palettes,spec=spec,changed_metas=[])
        state=maps[name]
        for dy,row in enumerate(spec["metas"]):
            for dx,meta in enumerate(row):
                assert state["grid"][spec["y"]+dy][spec["x"]+dx]==meta
        original=render(state["context"],spec["metas"]); foreground=render(state["context"],spec["metas"],(1,))
        assert list(foreground.getbbox())==spec["bounds"], f'Unexpected original occupied bounds: {spec["asset"]}'
        relative=f'images/{spec["image"]}.png'; url=f"https://huggingface.co/datasets/{DATASET}/resolve/{REVISION}/{relative}"
        if catalog:
            source=(catalog/relative).read_bytes()
        else:
            with urllib.request.urlopen(url,timeout=60) as response: source=response.read()
        assert digest(source)==spec["image"], "Published image hash mismatch"
        native,colors,conversion=native_image(source,spec)
        generated[spec["asset"]]=Image.open(BytesIO(source)).convert("RGBA")
        slot=state["palettes"].pop(0)
        overlay[f'{state["clone_root"]}/palettes/{slot:02}.pal']=palette_bytes(colors)
        sheet=Image.open(BytesIO(overlay[f'{state["clone_root"]}/tiles.png'])).copy()
        metas=bytearray(overlay[f'{state["clone_root"]}/metatiles.bin']); tile_indices=[]
        for my,row in enumerate(spec["metas"]):
            for mx,meta in enumerate(row):
                newrefs=[]
                for part in range(4):
                    ti=state["available"].pop(0); tile_indices.append(ti)
                    crop=native.crop((mx*16+part%2*8,my*16+part//2*8,mx*16+part%2*8+8,my*16+part//2*8+8))
                    sheet.paste(crop,((ti-512)%16*8,(ti-512)//16*8));newrefs.append(slot<<12|ti)
                offset=(meta-512)*16
                assert metas[offset:offset+8]==state["context"]["metas"][1][offset:offset+8]
                struct.pack_into("<4H",metas,offset+8,*newrefs);state["changed_metas"].append(meta)
        overlay[f'{state["clone_root"]}/tiles.png']=encoded(sheet,indexed=True)
        overlay[f'{state["clone_root"]}/metatiles.bin']=bytes(metas)
        asset=spec["asset"]; evidence[f"{asset}/reference.png"]=encoded(original)
        evidence[f"{asset}/reference-foreground.png"]=encoded(foreground)
        evidence[f"{asset}/native.png"]=encoded(native,indexed=True)
        evidence[f"{asset}/native.4bpp"]=tile_bytes(native)
        evidence[f"{asset}/palette.pal"]=palette_bytes(colors)
        evidence[f"{asset}/palette.gbapal"]=struct.pack("<16H",*(r//8|(g//8)<<5|(b//8)<<10 for r,g,b in colors))
        report["assets"].append({"id":spec.get("id",f'world-v2-{asset}-{spec["variation"]}'),"map":name,"position":[spec["x"],spec["y"]],"all_positions":spec.get("positions",[[spec["x"],spec["y"]]]),"metatiles":spec["metas"],"states":["idle"],"source_url":url,"source_sha256":digest(source),"native_sha256":digest(evidence[f"{asset}/native.png"]),"palette_slot":slot,"native_tile_indices":tile_indices,"conversion":conversion,"lower_background_refs":"byte-identical","metatile_attributes":"byte-identical"})
    # Explicitly requested native backdrop repair, separate from gallery art.
    # The peach floor already used below the original table is the only source.
    post=maps["HelixResearchPost"]
    meta_path=f'{post["clone_root"]}/metatiles.bin'
    metas=bytearray(overlay[meta_path])
    source_metas=post["context"]["metas"][1]
    floor_refs=struct.unpack_from("<4H",source_metas,(0x248-512)*16)
    assert floor_refs==(0x6218,)*4, "Reviewed native table-floor source changed"
    background_metas=[0x223,0x298,0x289,0x28a]
    changes=[]
    for meta in background_metas:
        offset=(meta-512)*16
        old_refs=struct.unpack_from("<4H",source_metas,offset)
        upper_before=bytes(metas[offset+8:offset+16])
        struct.pack_into("<4H",metas,offset,*floor_refs)
        assert bytes(metas[offset+8:offset+16])==upper_before
        post["changed_metas"].append(meta)
        positions=[[x,y] for y,row in enumerate(post["grid"]) for x,value in enumerate(row) if value==meta]
        assert positions, "Backdrop correction must bind existing map cells"
        changes.append({"metatile":meta,"lower_refs_before":list(old_refs),"lower_refs_after":list(floor_refs),"positions":positions})
    overlay[meta_path]=bytes(metas)
    repaired=context(game,"helix_assets_post",overlay)
    floor_pixels=render(post["context"],[[0x248]],(0,))
    assert floor_pixels.getchannel("A").getextrema()==(255,255)
    for meta in background_metas:
        lower=render(repaired,[[meta]],(0,))
        assert lower.tobytes()==floor_pixels.tobytes(), "Backdrop must reproduce the opaque source floor exactly"
    report["native_background_repair"]={"map":"HelixResearchPost","source_metatile":0x248,"source_layer":0,"source_refs":list(floor_refs),"source_pixels_sha256":digest(floor_pixels.tobytes()),"fully_opaque":True,"no_generated_pixels":True,"palette_changes":False,"upper_furniture_layers_preserved":True,"map_blocks_and_attributes_preserved":True,"metatiles":changes,"affected_metatile_definitions":len(changes),"affected_map_cells":sum(len(v["positions"]) for v in changes)}
    for asset in report["assets"]:
        if asset["id"]=="wave12-indoor-potted-tree-2026-v12":
            asset["lower_background_refs"]="top unchanged; bottom metatile uses separately documented original native peach floor"
    for name,state in maps.items():
        spec=state["spec"]; symbol=spec["symbol"]; layout=state["layout"]; clone=state["clone_root"]
        after=context(game,spec["clone"],overlay)
        evidence[f"{name}-after.png"]=encoded(render(after,state["grid"]))
        # Ensure every metatile outside the selected props renders identically.
        for row in state["grid"]:
            for meta in row:
                if meta not in state["changed_metas"]:
                    assert render(state["context"],[[meta]]).tobytes()==render(after,[[meta]]).tobytes()
        if name=="HelixLaboratory":
            layout=deepcopy(layout); layout.update(id="LAYOUT_HELIX_ASSETS_LABORATORY",name="HelixAssetsLaboratory_Layout",secondary_tileset=f"gTileset_{symbol}",border_filepath="data/layouts/HelixAssetsLaboratory/border.bin",blockdata_filepath="data/layouts/HelixAssetsLaboratory/map.bin")
            assert not any(v["id"]==layout["id"] for v in layouts["layouts"])
            layouts["layouts"].append(layout)
            overlay[layout["blockdata_filepath"]]=state["raw"]
            overlay[layout["border_filepath"]]=read(state["layout"]["border_filepath"])
            header=deepcopy(state["header"]); header["layout"]=layout["id"]
            overlay[f"data/maps/{name}/map.json"]=(json.dumps(header,indent=2)+"\n").encode()
        else:
            layout["secondary_tileset"]=f"gTileset_{symbol}"
        for filename in ("headers.h","graphics.h","metatiles.h"):
            path=f"src/data/tilesets/{filename}"
            if path not in overlay: overlay[path]=read(path)
        path="include/tilesets.h"
        if path not in overlay: overlay[path]=read(path)
        assert f"gTileset_{symbol}".encode() not in overlay[path]
        overlay[path]+=f"\nextern const struct Tileset gTileset_{symbol};\n".encode()
        overlay["src/data/tilesets/graphics.h"]+=(f'\n// Isolated Helix catalog batch 1; all other maps retain upstream art.\nconst u32 gTilesetTiles_{symbol}[] = INCGFX_U32("{clone}/tiles.png", ".4bpp.fastSmol", "-num_tiles 512 -Wnum_tiles");\nconst u16 gTilesetPalettes_{symbol}[][16] =\n{{\n'+"\n".join(f'    INCGFX_U16("{clone}/palettes/{i:02}.pal", ".gbapal"),' for i in range(16))+"\n};\n").encode()
        overlay["src/data/tilesets/metatiles.h"]+=f'\nconst u16 gMetatiles_{symbol}[] = INCBIN_U16("{clone}/metatiles.bin");\nconst u16 gMetatileAttributes_{symbol}[] = INCBIN_U16("{clone}/metatile_attributes.bin");\n'.encode()
        overlay["src/data/tilesets/headers.h"]+=f'\nconst struct Tileset gTileset_{symbol} =\n{{\n    .isCompressed = TRUE,\n    .isSecondary = TRUE,\n    .tiles = gTilesetTiles_{symbol},\n    .palettes = gTilesetPalettes_{symbol},\n    .metatiles = gMetatiles_{symbol},\n    .metatileAttributes = gMetatileAttributes_{symbol},\n    .callback = NULL,\n}};\n'.encode()
    overlay["data/layouts/layouts.json"]=(json.dumps(layouts,indent=2)+"\n").encode()
    contact=Image.new("RGB",(880,4*210),(104,115,112));draw=ImageDraw.Draw(contact)
    for i,spec in enumerate(selection):
        asset=spec["asset"];draw.text((10,i*210+5),asset,fill="white")
        for x,label,im in [(10,"Original",Image.open(BytesIO(evidence[f"{asset}/reference.png"])).convert("RGBA")),(230,"Published source (whole)",generated[asset]),(450,"Native foreground x4",Image.open(BytesIO(evidence[f"{asset}/native.png"])).convert("RGBA")),(660,"Native + original background",render(context(game,spec["clone"],overlay),spec["metas"]))]:
            draw.text((x,i*210+25),label,fill="white")
            if x==230: im.thumbnail((190,160),Image.Resampling.NEAREST)
            else: im=im.resize((im.width*4,im.height*4),Image.Resampling.NEAREST)
            contact.paste(im,(x,i*210+50),im)
    evidence["comparison.png"]=encoded(contact)
    report.update(substitutions=4,designs=4,object_positions=5,npc_designs=0,npc_positions=0,source_inputs=before,overlay_files={p:digest(v) for p,v in overlay.items()},evidence_files={p:digest(v) for p,v in evidence.items()},preserved={"map_blockdata":True,"metatile_attributes":True,"lower_layer_refs_except_requested_post_backdrop":True,"npc_events":True,"scripts":True,"source_tilesets":True})
    output.mkdir(parents=True)
    for prefix,files in (("overlay",overlay),("evidence",evidence)):
        for path,data in files.items():
            target=output/prefix/path;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
    (output/"conversion.json").write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
    if install:
        # Recheck all input files immediately before writing the staged overlay.
        for path,expected in before.items(): assert digest((game/path).read_bytes())==expected
        for path,data in overlay.items():
            target=game/path;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
    print(json.dumps({"output":str(output),"installed":install,"substitutions":4,"conversion_sha256":digest((output/"conversion.json").read_bytes())}))


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game",type=Path,required=True)
    parser.add_argument("--catalog",type=Path,help="Pinned export; omit to download only four hash-checked PNGs")
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--install",action="store_true")
    parser.add_argument("--table-variation",choices=["chalk_sage","slate_cobalt"],required=True)
    args=parser.parse_args()
    integrate(args.game,args.catalog,args.output,args.install,args.table_variation)
