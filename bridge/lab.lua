-- LAB1: bounded synthetic-assay transport; no simulation/connect in callbacks.
if labBridgeStop then labBridgeStop() end
local cfg = assert(BRIDGE_CONFIG)
local addr = assert(cfg.lab_mailbox)
assert(addr >= 0x02000000 and addr + 92 <= 0x02040000)
local conn, pending, lastIdentity, previousFrame
local incoming, outgoing, generation, running, owned = "", "", 0, true, {}
local base = cfg.session:sub(1,32) .. string.format("%08x%08x",os.time() & 0xFFFFFFFF,math.random(0,0x7FFFFFFF))
local function sameRom()
    return (emu:checksum(C.CHECKSUM.CRC32):gsub(".",function(c) return string.format("%02x",c:byte()) end)) == cfg.rom_crc32:lower()
end
assert(sameRom(), "LAB1 ROM mismatch")
local function header()
    if emu:read32(addr) ~= 0x3142414C or emu:read16(addr+4) ~= 1 then return nil end
    local bytes={}
    for i=8,83 do bytes[#bytes+1]=string.format("%02x",emu:read8(addr+i)) end
    return table.concat(bytes)
end
local function matches()
    return pending and emu:read16(addr+6)==1 and header()==pending.context
end
local function queue(line)
    if #outgoing+#line>1280 then return false end
    outgoing=outgoing..line
    return true
end
local function cancel()
    if pending and conn then queue("LAB1|CANCEL|"..pending.identity.."\n") end
    pending=nil
end
local function disconnect()
    if matches() then emu:write16(addr+6,4) end
    cancel()
    if conn then conn:close() end
    conn=nil
    collectgarbage("collect") -- mGBA 0.10.5 descriptor lifetime workaround.
    incoming,outgoing="",""
end
function labBridgeConnect()
    if not running then return false end
    disconnect()
    assert(sameRom(), "LAB1 ROM mismatch")
    generation=generation+1
    lastIdentity=nil
    conn=socket.connect("127.0.0.1",cfg.port)
    return conn~=nil
end
function labBridgeDisconnect() disconnect() end
function labBridgeStop()
    if not running then return end
    disconnect(); running=false
    for _,id in ipairs(owned) do callbacks:remove(id) end
    owned={}
end
local function invalidate()
    if matches() then emu:write16(addr+6,4) end
    cancel(); generation=generation+1; lastIdentity=nil; incoming=""
end
local function receive(line)
    if #line>639 then disconnect(); return end
    local f={}
    for value in (line.."|"):gmatch("(.-)|") do f[#f+1]=value end
    if #f~=6 or f[1]~="LAB1" then disconnect(); return end
    if not matches() or f[3].."|"..f[4]~=pending.identity then return end
    if f[2]=="ERROR" and f[5]=="" and f[6]=="" then
        emu:write16(addr+6,4);pending=nil;return
    end
    if f[2]~="OK" or #f[5]~=16 or f[5]:find("[^a-f0-9]")
        or #f[6]~=64 or f[6]:find("[^a-f0-9]") then disconnect();return end
    -- Exactly eight payload bytes; native independently revalidates current
    -- save/companion/quest/model, all numbers and inventory before any effect.
    for i=0,7 do emu:write8(addr+84+i,tonumber(f[5]:sub(2*i+1,2*i+2),16)) end
    emu:write16(addr+6,2) -- Publish last.
    pending=nil
end
local function frame()
    local n=emu:currentFrame()
    if previousFrame and n<previousFrame then invalidate() end
    previousFrame=n
    if pending and not matches() then cancel() end
    local h=header()
    if h and emu:read16(addr+6)==1 and h~=lastIdentity then
        lastIdentity=h
        if not conn then emu:write16(addr+6,4)
        else
            pending={context=h,identity=base.."-"..generation.."|"..h}
            if not queue("LAB1|REQ|"..pending.identity.."\n") then disconnect() end
        end
    end
    if not conn then return end
    if #outgoing>0 then
        local sent,err=conn:send(outgoing)
        if sent then outgoing=outgoing:sub(sent+1)
        elseif err~=socket.ERRORS.AGAIN then disconnect();return end
    end
    local ready,err=conn:hasdata()
    if err then disconnect();return end
    if ready then
        local data,e=conn:receive(640)
        if not data then
            if e~=socket.ERRORS.AGAIN then disconnect() end
            return
        end
        incoming=incoming..data
        if #incoming>1280 then disconnect();return end
    end
    local pos=incoming:find("\n",1,true)
    if pos then
        local line=incoming:sub(1,pos-1);incoming=incoming:sub(pos+1);receive(line)
    elseif #incoming>639 then disconnect() end
end
owned[#owned+1]=callbacks:add("frame",frame)
owned[#owned+1]=callbacks:add("reset",function() invalidate();previousFrame=nil end)
owned[#owned+1]=callbacks:add("stop",labBridgeStop)
owned[#owned+1]=callbacks:add("crashed",labBridgeStop)
labBridgeConnect()
