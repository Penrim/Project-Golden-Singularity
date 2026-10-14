-- mGBA test bridge: line-based TCP protocol on port 61337 so Python can drive the emulator.
-- Commands (one per line, reply is one line):
--   ping                      -> pong
--   frame                     -> current frame number
--   wait N                    -> run N frames, then "ok"
--   keys MASK                 -> hold key mask (A=1 B=2 Select=4 Start=8 Right=16 Left=32 Up=64 Down=128 R=256 L=512)
--   r8/r16/r32 ADDR           -> value (decimal)
--   rr ADDR LEN               -> hex bytes
--   w8/w16/w32 ADDR VALUE     -> ok
--   shot PATH                 -> ok (PNG screenshot)
--   save PATH / load PATH     -> ok (save state file)
--   reset                     -> ok
local PORT = tonumber(os and os.getenv and os.getenv("GSMERGE_PORT") or "") or 61337   -- parallel test runs
local server = nil
local client = nil
local buf = ""
local waitUntil = nil
hits, hitregs = {}, {}
watchRange, watchId = nil, nil
allHits, allId = {}, nil

function armWatch()
	if not watchRange or watchId then return end
	watchId = emu:setRangeWatchpoint(function()
		local pc = emu:readRegister("pc")
		if not hits[pc] then
			hits[pc] = 0
			local t = {}
			for _, r in ipairs({"r0","r1","r2","r3","r4","r5","r6","r7","lr"}) do
				t[#t + 1] = string.format("%s=%08x", r, emu:readRegister(r))
			end
			hitregs[pc] = table.concat(t, ",")
		end
		hits[pc] = hits[pc] + 1
		emu:clearBreakpoint(watchId)
		watchId = nil
	end, watchRange[1], watchRange[2], C.WATCHPOINT_TYPE.READ)
end

local function reply(s)
	if client then client:send(s .. "\n") end
end

local function handle(line)
	local cmd, a, b = line:match("^(%S+)%s*(%S*)%s*(%S*)")
	if cmd == "shot" or cmd == "save" or cmd == "load" or cmd == "ptrdump" then a = line:match("^%S+%s+(.-)%s*$") end -- paths may contain spaces
	if cmd == "ping" then reply("pong")
	elseif cmd == "frame" then reply(tostring(emu:currentFrame()))
	elseif cmd == "wait" then waitUntil = emu:currentFrame() + tonumber(a); return
	elseif cmd == "keys" then emu:setKeys(tonumber(a)); reply("ok")
	elseif cmd == "r8" then reply(tostring(emu:read8(tonumber(a))))
	elseif cmd == "r16" then reply(tostring(emu:read16(tonumber(a))))
	elseif cmd == "r32" then reply(tostring(emu:read32(tonumber(a))))
	elseif cmd == "rr" then
		local s = emu:readRange(tonumber(a), tonumber(b))
		reply((s:gsub(".", function(c) return string.format("%02x", c:byte()) end)))
	elseif cmd == "w8" then emu:write8(tonumber(a), tonumber(b)); reply("ok")
	elseif cmd == "w16" then emu:write16(tonumber(a), tonumber(b)); reply("ok")
	elseif cmd == "w32" then emu:write32(tonumber(a), tonumber(b)); reply("ok")
	elseif cmd == "dumpmem" then
		-- dumpmem ADDR LEN PATH : write memory to a file (single frame, so state is consistent)
		local addr, len, path = line:match("^%S+%s+(%S+)%s+(%S+)%s+(.-)%s*$")
		local fh = io.open(path, "wb")
		fh:write(emu:readRange(tonumber(addr), tonumber(len)))
		fh:close()
		reply("ok")
	elseif cmd == "record" then
		-- record N PREFIX : dump VRAM/palette/OAM/IO to PREFIX<frame>_<region>.bin on each of the next N frames
		local n, prefix = line:match("^%S+%s+(%S+)%s+(.-)%s*$")
		recLeft, recPrefix = tonumber(n), prefix
		waitUntil = emu:currentFrame() + recLeft
	elseif cmd == "shot" then emu:screenshot(a); reply("ok")
	elseif cmd == "save" then emu:saveStateFile(a); reply("ok")
	elseif cmd == "load" then emu:loadStateFile(a); reply("ok")
	elseif cmd == "reset" then emu:reset(); reply("ok")
	elseif cmd == "pc" then reply(tostring(emu:readRegister("pc")))
	elseif cmd == "regs" then
		local t = {}
		for _, r in ipairs({"r0","r1","r2","r3","r4","r5","r6","r7","r8","r9","r10","r11","r12","sp","lr","pc","cpsr"}) do
			t[#t + 1] = string.format("%s=%08x", r, emu:readRegister(r))
		end
		reply(table.concat(t, " "))
	elseif cmd == "watch" then
		-- range read watchpoint: record first hit, disarm, re-arm next frame (keeps tight loops cheap)
		watchRange = {tonumber(a), tonumber(b)}
		armWatch()
		reply("ok")
	elseif cmd == "watchall" then
		-- persistent counting watchpoint (expensive; use for a few frames only)
		allId = emu:setRangeWatchpoint(function()
			local pc = emu:readRegister("pc")
			allHits[pc] = (allHits[pc] or 0) + 1
		end, tonumber(a), tonumber(b), C.WATCHPOINT_TYPE.READ)
		reply("ok")
	elseif cmd == "unwatchall" then
		if allId then emu:clearBreakpoint(allId); allId = nil end
		local t = {}
		for pc, n in pairs(allHits) do t[#t + 1] = string.format("%08x:%d", pc, n) end
		allHits = {}
		reply(table.concat(t, ";"))
	elseif cmd == "acclog" then
		-- log up to N accesses (reads+writes) in [a, b] with pc/address/value: "acclog LO HI"
		accLog = {}
		local function mk(kind)
			return function(info)
				if #accLog < 400 then
					accLog[#accLog + 1] = string.format("%d,%s,%08x,%08x,%s,%s", emu:currentFrame(), kind,
						emu:readRegister("pc"), info.address, tostring(info.oldValue), tostring(info.newValue))
				end
			end
		end
		accIds = { emu:setRangeWatchpoint(mk("R"), tonumber(a), tonumber(b), C.WATCHPOINT_TYPE.READ),
		           emu:setRangeWatchpoint(mk("W"), tonumber(a), tonumber(b), C.WATCHPOINT_TYPE.WRITE) }
		reply("ok")
	elseif cmd == "acclogf" then
		-- like acclog but streams every access to a file (survives crashes): acclogf LO HI PATH
		local lo, hi, path = line:match("^%S+%s+(%S+)%s+(%S+)%s+(.-)%s*$")
		local fh = io.open(path, "w")
		local n = 0
		local function mk(kind)
			return function(info)
				n = n + 1
				if n <= 50000 then
					fh:write(string.format("%d,%s,%08x,%08x,%08x,%s\n", emu:currentFrame(), kind,
						emu:readRegister("pc"), emu:readRegister("lr"), info.address, tostring(info.oldValue)))
					fh:flush()
				end
			end
		end
		accIds = { emu:setRangeWatchpoint(mk("R"), tonumber(lo), tonumber(hi), C.WATCHPOINT_TYPE.READ) }
		reply("ok")
	elseif cmd == "acclogwf" then
		-- like acclogf but for WRITES: acclogwf LO HI PATH (logs pc, lr, address, new value)
		local lo, hi, path = line:match("^%S+%s+(%S+)%s+(%S+)%s+(.-)%s*$")
		local fh = io.open(path, "w")
		local n = 0
		accIds = { emu:setRangeWatchpoint(function(info)
			n = n + 1
			if n <= 50000 then
				fh:write(string.format("%d,W,%08x,%08x,%08x,%s;", emu:currentFrame(), emu:readRegister("pc"),
					emu:readRegister("lr"), info.address, tostring(info.newValue)))
				fh:write(string.char(10))
				fh:flush()
			end
		end, tonumber(lo), tonumber(hi), C.WATCHPOINT_TYPE.WRITE) }
		reply("ok")
	elseif cmd == "accdump" then
		for _, id in ipairs(accIds or {}) do emu:clearBreakpoint(id) end
		accIds = nil
		reply(table.concat(accLog or {}, ";"))
	elseif cmd == "forceret" then
		-- forceret ADDR VALUE : at ADDR (first time hit) set r0 = VALUE (e.g. force an encounter result)
		local addr, val = tonumber(a), tonumber(b)
		local id
		id = emu:setBreakpoint(function()
			if emu:readRegister("r0") == 0 then
				emu:writeRegister("r0", val)
				emu:clearBreakpoint(id)
			end
		end, addr)
		reply(tostring(id))
	elseif cmd == "bpwrite" then
		-- bpwrite ADDR WADDR VALUE : when ADDR executes (first time), write32 VALUE at WADDR
		local addr, waddr, val = line:match("^%S+%s+(%S+)%s+(%S+)%s+(%S+)")
		local id
		id = emu:setBreakpoint(function()
			emu:write32(tonumber(waddr), tonumber(val))
			emu:clearBreakpoint(id)
		end, tonumber(addr))
		reply(tostring(id))
	elseif cmd == "bplog" then
		-- bplog ADDR PATH : every time ADDR executes, append registers to PATH (survives crashes)
		local addr, path = line:match("^%S+%s+(%S+)%s+(.-)%s*$")
		emu:setBreakpoint(function()
			local fh = io.open(path, "a")
			local t = {}
			for _, r in ipairs({"r0","r1","r2","r3","r4","r5","sp","lr","pc"}) do
				t[#t + 1] = string.format("%s=%08x", r, emu:readRegister(r))
			end
			fh:write(string.format("%d %s\n", emu:currentFrame(), table.concat(t, " ")))
			fh:close()
		end, tonumber(addr))
		reply("ok")
	elseif cmd == "watchwidth" then
		-- watchwidth LISTFILE OUTFILE : read watchpoints on the 4-byte words listed (one hex address per line);
		-- appends "address width pc" for each new (address, width) combination to OUTFILE
		-- (one range watchpoint over the whole span + a lookup table; one watchpoint per word is far too slow)
		local list, out = line:match("^%S+%s+(%S+)%s+(.-)%s*$")
		local seenW, words = {}, {}
		local lo, hi = 0xFFFFFFFF, 0
		for l in io.lines(list) do
			local addr = tonumber(l, 16)
			if addr then
				words[addr] = true
				if addr < lo then lo = addr end
				if addr + 3 > hi then hi = addr + 3 end
			end
		end
		local fh = io.open(out, "a")
		emu:setRangeWatchpoint(function(info)
			local w = info.address - (info.address % 4)
			if words[w] then
				local key = string.format("%08x %d", w, info.width or 0)
				if not seenW[key] then
					seenW[key] = true
					fh:write(string.format("%s %08x %08x\n", key, info.address, emu:readRegister("pc")))
					fh:flush()
				end
			end
		end, lo, hi, C.WATCHPOINT_TYPE.READ)
		reply("ok")
	elseif cmd == "ptrprobe" then
		-- ptrprobe LISTFILE LO HI : classify the listed 4-byte words (relocated pointer candidates) while the game
		-- runs. A watchpoint on [LO, HI] sees every read there; per candidate: narrow (8/16-bit) reads, 32-bit
		-- reads, and "used" = a later read (within 96 reads) lands in [value, value + 0x800). ptrdump PATH writes it.
		local list, lo, hi = line:match("^%S+%s+(%S+)%s+(%S+)%s+(%S+)")
		probe = {}
		for l in io.lines(list) do
			local addr = tonumber(l, 16)
			if addr then probe[addr] = {narrow = 0, wide = 0, used = 0} end
		end
		local pending = {}
		local readNo = 0
		emu:setRangeWatchpoint(function(info)
			readNo = readNo + 1
			local a = info.address
			for i = #pending, 1, -1 do
				local p = pending[i]
				if readNo - p[3] > 96 then
					table.remove(pending, i)
				elseif a >= p[2] and a < p[2] + 0x800 then
					probe[p[1]].used = probe[p[1]].used + 1
					table.remove(pending, i)
				end
			end
			local w = a - (a % 4)
			local s = probe[w]
			if s then
				if (info.width or 4) < 4 then
					s.narrow = s.narrow + 1
				else
					s.wide = s.wide + 1
					local v = emu:read32(w) & 0xFFFFFFFE
					pending[#pending + 1] = {w, v, readNo}
				end
			end
		end, tonumber(lo), tonumber(hi), C.WATCHPOINT_TYPE.READ)
		reply("ok")
	elseif cmd == "ptrdump" then
		local fh = io.open(a, "w")
		for addr, s in pairs(probe or {}) do
			if s.narrow + s.wide > 0 then
				fh:write(string.format("%08x %d %d %d\n", addr, s.narrow, s.wide, s.used))
			end
		end
		fh:close()
		reply("ok")
	elseif cmd == "bponce" then
		-- bponce ADDR PATH : like bplog, but only the first hit (safe for addresses inside crash loops)
		local addr, path = line:match("^%S+%s+(%S+)%s+(.-)%s*$")
		local id
		id = emu:setBreakpoint(function()
			emu:clearBreakpoint(id)
			local fh = io.open(path, "a")
			local t = {}
			for _, r in ipairs({"r0","r1","r2","r3","r4","r5","r6","r7","r12","sp","lr","pc","cpsr"}) do
				t[#t + 1] = string.format("%s=%08x", r, emu:readRegister(r))
			end
			fh:write(string.format("%d %08x %s\n", emu:currentFrame(), tonumber(addr), table.concat(t, " ")))
			fh:close()
		end, tonumber(addr))
		reply("ok")
	elseif cmd == "callafter" then
		-- callafter FUNC TARGET : when FUNC is next called, let it run; at its return site call TARGET
		-- (Thumb), which then returns to that same return site.
		local func, target = tonumber(a), tonumber(b)
		local id1
		id1 = emu:setBreakpoint(function()
			emu:clearBreakpoint(id1)
			local ret = emu:readRegister("lr")
			local id2
			id2 = emu:setBreakpoint(function()
				emu:clearBreakpoint(id2)
				emu:writeRegister("lr", ret | 1)
				emu:writeRegister("pc", target & ~1)
			end, ret & ~1)
		end, func)
		reply("ok")
	elseif cmd == "hits" then
		local t = {}
		for pc, n in pairs(hits) do t[#t + 1] = string.format("%08x:%d:%s", pc, n, hitregs[pc]) end
		hits, hitregs = {}, {}
		reply(table.concat(t, ";"))
	else reply("err unknown " .. tostring(cmd)) end
end

local function pump()
	if not client then return end
	while true do
		local p, err = client:receive(4096)
		if p then
			buf = buf .. p
		else
			if err ~= socket.ERRORS.AGAIN then client = nil end
			break
		end
	end
end

local function recordFrame()
	local f = emu:currentFrame()
	for _, r in ipairs({{"vram", 0x06000000, 0x18000}, {"pal", 0x05000000, 0x400}, {"oam", 0x07000000, 0x400},
	                    {"io", 0x04000000, 0x60}}) do
		local fh = io.open(string.format("%s%05d_%s.bin", recPrefix, f, r[1]), "wb")
		fh:write(emu:readRange(r[2], r[3]))
		fh:close()
	end
	emu:screenshot(string.format("%s%05d.png", recPrefix, f))
	recLeft = recLeft - 1
end

callbacks:add("frame", function()
	armWatch()
	if recLeft and recLeft > 0 then recordFrame() end
	if waitUntil then
		if emu:currentFrame() >= waitUntil then waitUntil = nil; reply("ok") else return end
	end
	pump()
	while not waitUntil do
		local line, rest = buf:match("^([^\n]*)\n(.*)$")
		if not line then break end
		buf = rest
		handle(line:gsub("\r", ""))
	end
end)

server = socket.bind(nil, PORT)
server:listen()
server:add("received", function()
	local c = server:accept()
	if c then client = c; buf = "" end
end)
console:log("bridge listening on " .. PORT)
