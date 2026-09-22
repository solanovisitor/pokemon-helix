#!/usr/bin/env python3
"""Verify the linked four-asset batch in an exact GBA ROM and its ELF symbols.

Requires Pillow 11.3.0, the matching built game checkout and ARM toolchain.
This checks compiled bytes/bindings; gameplay acceptance still requires mGBA.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
import shutil
import struct
import subprocess
import tempfile

from PIL import Image


def hash_bytes(raw):
    return sha256(raw).hexdigest()


def toolchain_nm(path):
    if path:
        for candidate in (path/"bin/arm-none-eabi-nm",path/"arm-none-eabi-nm",path):
            if candidate.is_file(): return candidate
        raise ValueError("No arm-none-eabi-nm in toolchain path")
    found=shutil.which("arm-none-eabi-nm")
    if not found: raise ValueError("Pass --toolchain or put arm-none-eabi-nm on PATH")
    return Path(found)


def symbols(elf,nm):
    result=subprocess.run([str(nm),"-S","--defined-only",str(elf)],check=True,capture_output=True,text=True)
    output={}
    for line in result.stdout.splitlines():
        fields=line.split()
        if len(fields)==4:
            address,size,kind,name=fields;output[name]=(int(address,16),int(size,16))
        elif len(fields)==3:
            address,kind,name=fields;output[name]=(int(address,16),None)
    return output


def native_tiles(path):
    image=Image.open(path)
    assert image.mode=="P" and image.width%8==0 and image.height%8==0
    output=bytearray()
    for ty in range(image.height//8):
        for tx in range(image.width//8):
            for y in range(8):
                for x in range(0,8,2):
                    a=image.getpixel((tx*8+x,ty*8+y));b=image.getpixel((tx*8+x+1,ty*8+y))
                    assert 0<=a<16 and 0<=b<16
                    output.append(a|(b<<4))
    assert len(output)==512*32, "This batch explicitly binds 512 native tile slots"
    return bytes(output)


def palette_binary(path):
    lines=path.read_text().splitlines()
    assert lines[:3]==["JASC-PAL","0100","16"]
    values=[]
    for line in lines[3:19]:
        r,g,b=map(int,line.split());values.append((r>>3)|((g>>3)<<5)|((b>>3)<<10))
    assert len(values)==16
    return struct.pack("<16H",*values)


def verify(game,rom_path,elf_path,nm):
    rom=rom_path.read_bytes(); syms=symbols(elf_path,nm)
    def address(name):
        assert name in syms,f"Missing linked symbol: {name}"
        return syms[name][0]
    def memory(pointer,length):
        offset=pointer-0x08000000
        assert offset>=0 and offset+length<=len(rom),f"Out-of-ROM pointer: {pointer:08x}"
        return rom[offset:offset+length]
    def at(name,length):
        if syms[name][1] is not None: assert syms[name][1]>=length,f"Short linked array: {name}"
        return memory(address(name),length)
    def check(name,expected):
        assert at(name,len(expected))==expected,f"Linked ROM bytes differ: {name}"
        return {"symbol":name,"rom_address":f"0x{address(name):08x}","bytes":len(expected),"sha256":hash_bytes(expected)}
    def ptr(pointer): return struct.unpack("<I",memory(pointer,4))[0]
    results=[]
    for suffix,folder in (("HelixAssetsPost","helix_assets_post"),("HelixAssetsLab","helix_assets_lab")):
        directory=game/f"data/tilesets/secondary/{folder}"
        raw=native_tiles(directory/"tiles.png")
        built=game/f"build/assets/data/tilesets/secondary/{folder}/tiles.png_num_tiles_512__Wnum_tiles.4bpp"
        assert built.read_bytes()==raw,"Build cache 4bpp does not match source PNG"
        compressed=built.with_name(built.name+".fastSmol").read_bytes()
        # Recompress independently in temporary files to catch stale build cache.
        compressor=game/"tools/compresSmol/compresSmol"
        with tempfile.TemporaryDirectory(prefix="helix-compiled-assets-") as temporary:
            source=Path(temporary)/"source.4bpp"; dest=Path(temporary)/"source.fastSmol"
            source.write_bytes(raw)
            subprocess.run([str(compressor.resolve()),"-w",str(source),str(dest),"false","false","false"],check=True,capture_output=True)
            assert dest.read_bytes()==compressed,"Build compression differs from current native pixels"
        arrays=[check(f"gTilesetTiles_{suffix}",compressed),check(f"gMetatiles_{suffix}",(directory/"metatiles.bin").read_bytes()),check(f"gMetatileAttributes_{suffix}",(directory/"metatile_attributes.bin").read_bytes())]
        palettes=b"".join(palette_binary(directory/f"palettes/{i:02}.pal") for i in range(16))
        arrays.append(check(f"gTilesetPalettes_{suffix}",palettes))
        tileset=at(f"gTileset_{suffix}",24)
        assert tileset[:4]==bytes([1,1,0,0]),"Expected compressed secondary tileset with unchanged light flags"
        expected=[address(f"gTilesetTiles_{suffix}"),address(f"gTilesetPalettes_{suffix}"),address(f"gMetatiles_{suffix}"),address(f"gMetatileAttributes_{suffix}"),0]
        assert list(struct.unpack_from("<5I",tileset,4))==expected,"Tileset pointers/callback differ"
        results.append({"tileset":f"gTileset_{suffix}","native_uncompressed_sha256":hash_bytes(raw),"compressed_source_rebuilt_exactly":True,"arrays":arrays,"tileset_pointers_verified":True})
    layouts=json.loads((game/"data/layouts/layouts.json").read_text())
    constants=(game/"include/constants/layouts.h").read_text()
    bindings=[]
    for name,expected_tileset in (("HelixResearchPost","gTileset_HelixAssetsPost"),("HelixLaboratory","gTileset_HelixAssetsLab")):
        header=json.loads((game/f"data/maps/{name}/map.json").read_text())
        layout=next(row for row in layouts["layouts"] if row["id"]==header["layout"])
        layout_name=layout["name"]; data=at(layout_name,28)
        width,height,border,mapdata,primary,secondary=struct.unpack_from("<6I",data)
        assert (width,height)==(layout["width"],layout["height"])
        assert primary==address(layout["primary_tileset"])
        assert secondary==address(expected_tileset)==address(layout["secondary_tileset"])
        for pointer,field in ((border,"border_filepath"),(mapdata,"blockdata_filepath")):
            expected=(game/layout[field]).read_bytes()
            assert memory(pointer,len(expected))==expected,"Compiled layout pixels/collisions differ from source"
        layout_id=int(re.search(r"^#define "+re.escape(header["layout"])+r" +(\d+)$",constants,re.M)[1])
        assert ptr(address(name))==address(layout_name),"Map header layout pointer differs"
        assert struct.unpack("<H",memory(address(name)+0x12,2))[0]==layout_id,"Map header layout id differs"
        assert ptr(address("gMapLayouts")+(layout_id-1)*4)==address(layout_name),"Layout table binding differs"
        bindings.append({"map":name,"layout":layout_name,"layout_id":layout_id,"secondary_tileset":expected_tileset,"map_header_and_layout_table_verified":True,"map_and_border_bytes_verified":True})
    return {"schema":1,"status":"passed-compiled-native-asset-bindings","rom_sha256":hash_bytes(rom),"elf_sha256":hash_bytes(elf_path.read_bytes()),"abi_global_fieldmap_sha256":hash_bytes((game/"include/global.fieldmap.h").read_bytes()),"abi_offsets":{"Tileset_pointers":4,"Tileset_size":24,"MapLayout_secondaryTileset":20,"MapHeader_layoutId":18},"tilesets":results,"map_bindings":bindings,"runtime_acceptance":"requires separate inspected mGBA screenshots and state assertions"}


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game",type=Path,required=True)
    parser.add_argument("--rom",type=Path,required=True)
    parser.add_argument("--elf",type=Path,required=True)
    parser.add_argument("--toolchain",type=Path)
    parser.add_argument("--output",type=Path)
    args=parser.parse_args();result=verify(args.game.resolve(),args.rom,args.elf,toolchain_nm(args.toolchain))
    text=json.dumps(result,indent=2,sort_keys=True)+"\n"
    if args.output:
        assert not args.output.exists(),"Use a fresh compiled-verification receipt"
        args.output.write_text(text)
    print(text,end="")
