-- Playthrough replay for Golden Sun (USA): plays a recorded input movie on the original ROM ("ref") and replays
-- it on the GS1 part of the merged cartridge game step by game step ("align").
-- Started by tools/playthrough/playthrough.py.
--
-- RAM words used (GS1 USA; identical in the merged cartridge, which relocates only ROM addresses by +0x01000000):
--   STEP  0x03001E40  +1 per main-loop iteration (one game step); does not move while a load takes extra frames
--   VBL   0x03001800  +1 per VBlank interrupt, i.e. every frame; some game code reads it
--   SEED  0x03001CB4  random seed, x' = x * 0x41C64E6D + 0x3039; only the routine at 0x08004458 writes it
--                     (write watchpoint on the word: one store, 0x0800446A)
--   SCENE 0x02000400  current scene (map) number
-- These were identified from emulator traces of the original ROM (counter behaviour, write watchpoints).
--
-- Why "by game step": the merged cartridge recompresses some map code, so a few loads take 1-3 frames more or less
-- than on the original. A movie replayed frame by frame would then press buttons at the wrong game step. Here every
-- input of the reference is applied at the game step it was applied at on the original; VBL is set back to the
-- reference value at the first frame of each step.
--
-- Some scenes call the random routine from an HBlank interrupt (one call per scanline). How many of those calls
-- fall into one game step depends on exact CPU cycle timing, which the merged cartridge cannot reproduce (e.g. the
-- sound mixer load differs while the music is a few frames out of phase). The reference pass finds these scenes
-- itself (sampled breakpoint on the random routine: one caller with one call per scanline on >= 32 scanlines in
-- one step) and the replay realigns the seed in them when it is at most 16 calls off ("rngfix" lines). Any other
-- difference of the seed is a failure.
--
-- Line protocol on a TCP socket (port from env GSMERGE_PORT), one reply line per command; fields are separated by
-- spaces, or by "|" (e.g. "shot|C:/path with spaces/x.png"):
--   ping | frame | wait N | keys MASK | r32 A | rr A N | w32 A V | shot PATH | reset | load PATH | save PATH
--   ref MOVIE OUT N           play MOVIE ("mask frames" lines, emulator-frame indexed) from the current state
--   align TRACE OUT N S       replay the reference TRACE by game step; trace frames 0..S-1 were already played
--   refstate MOVIE OUT N ST / alignstate TRACE OUT N ST    resume from resume point ST (ST.ss + ST.txt)
-- Outputs: OUT.trace (per frame <I2 keys, <I4 STEP, <I4 VBL, <I4 SEED), OUT.snap (RAM after every N-th step),
-- OUT_<step>.png (screens of steps g, g+1, g+2 for g % N == 0), OUT.log, OUT.scanrng (ref only).
-- Reply: "done <frames> <last step>" or "err ...".
-- Env: PT_SAVE=K resume point every K steps, PT_STOP=g stop at step g, PT_RNG=addr of the random routine (ref:
-- scanline detection), PT_SCANRNG=file of scanline-RNG scenes (align), PT_DUMP=a-b video memory of steps a..b,
-- PT_RAMDUMP=g all RAM after step g, PT_BP=addr + PT_BPSTEPS=a-b log "step lr seed scanline" per hit.
local PORT = tonumber(os.getenv("GSMERGE_PORT") or "") or 61337
local STEP, VBL, SEED, SCENE, VCOUNT = 0x03001E40, 0x03001800, 0x03001CB4, 0x02000400, 0x04000006
local SAMPLE_EVERY, SCANLINE_MIN, MAX_SHIFT = 16, 32, 16

local function lcgAdvance(s, n)
	for _ = 1, n do s = (s * 0x41C64E6D + 0x3039) & 0xFFFFFFFF end
	return s
end
-- number of random calls that turn seed a into seed b (0..limit), or nil
local function lcgDist(a, b, limit)
	for n = 0, limit do
		if a == b then return n end
		a = (a * 0x41C64E6D + 0x3039) & 0xFFFFFFFF
	end
	return nil
end

local server, client, buf, waitUntil = nil, nil, "", nil
local play = nil

local function reply(s) if client then client:send(s .. "\n") end end
local function env(name) return os.getenv(name) or "" end

local function snapshot()
	-- EWRAM 0x02000000..0x02001000 (story flags, game state, party, inventory) + IWRAM 0x03001800..0x03002000
	return emu:readRange(0x02000000, 0x1000) .. emu:readRange(0x03001800, 0x800)
end

local function openOut(p, out, n)
	p.n, p.out, p.frames = n, out, 0
	p.trace = io.open(out .. ".trace", "wb"); p.tbuf = {}
	p.snap = io.open(out .. ".snap", "wb")
	p.log = io.open(out .. ".log", "w")
	p.cprev = emu:read32(STEP)
	p.stop = tonumber(env("PT_STOP"))
	p.save = tonumber(env("PT_SAVE"))
	p.ramdump = tonumber(env("PT_RAMDUMP"))
	local d0, d1 = env("PT_DUMP"):match("(%d+)-(%d+)")
	p.d0, p.d1 = tonumber(d0), tonumber(d1)
	local b0, b1 = env("PT_BPSTEPS"):match("(%d+)-(%d+)")
	if tonumber(env("PT_BP")) and b0 then
		p.bp, p.b0, p.b1 = tonumber(env("PT_BP")), tonumber(b0), tonumber(b1)
		p.bpf = io.open(out .. "_bp.txt", "w")
	end
end

local function closeOut(p, msg)
	if p.rngbp then emu:clearBreakpoint(p.rngbp); p.rngbp = nil end
	if p.bpid then emu:clearBreakpoint(p.bpid); p.bpid = nil end
	p.trace:write(table.concat(p.tbuf)); p.trace:close(); p.snap:close()
	p.log:write(msg .. "\n"); p.log:close()
	if p.bpf then p.bpf:close() end
	if p.scan then
		local fh = io.open(p.out .. ".scanrng", "w")
		for scene, step in pairs(p.scan) do fh:write(string.format("%d %d\n", scene, step)) end
		fh:close()
	end
	play = nil
	reply(msg)
end

-- debugging aid: caller log of one address, armed only around the requested steps (breakpoints slow mGBA down)
local function callerLog(p, c)
	if not p.bp then return end
	if not p.bpid and c >= p.b0 - 1 and c <= p.b1 then
		local fh, b0, b1 = p.bpf, p.b0, p.b1
		p.bpid = emu:setBreakpoint(function()
			local s = emu:read32(STEP)
			if s >= b0 and s <= b1 then
				fh:write(string.format("%d %08x %08x %d %08x\n", s, emu:readRegister("lr"), emu:read32(SEED),
					emu:read16(VCOUNT), emu:readRegister("cpsr")))
			end
		end, p.bp)
	elseif p.bpid and c > p.b1 then
		emu:clearBreakpoint(p.bpid); p.bpid = nil; p.bp = nil
	end
end

-- reference pass: every SAMPLE_EVERY-th step, record which scanlines each caller of the random routine runs on
local function scanlineSample(p, c, adv)
	if not p.rng or not adv then return end
	if p.rngbp then
		emu:clearBreakpoint(p.rngbp); p.rngbp = nil
		for _, t in pairs(p.lines) do
			local k = 0
			for _ in pairs(t.lines) do k = k + 1 end
			-- one call per scanline on many lines = per-scanline interrupt handler; a main-loop burst puts several
			-- calls on each line (e.g. battles: 64 calls on 16 lines) and is not accepted
			if k >= SCANLINE_MIN and t.calls <= k + k // 8 + 2 and not p.scan[p.sscene] then
				p.scan[p.sscene] = p.sstep
				p.log:write(string.format("scanline-rng scene %d step %d (%d calls on %d lines)\n", p.sscene, p.sstep,
					t.calls, k))
			end
		end
	end
	if c % SAMPLE_EVERY == 0 then
		local callers = {}
		p.lines, p.sscene, p.sstep = callers, emu:read16(SCENE), c
		p.rngbp = emu:setBreakpoint(function()
			local lr = emu:readRegister("lr")
			local t = callers[lr]
			if not t then t = {calls = 0, lines = {}}; callers[lr] = t end
			t.calls = t.calls + 1
			t.lines[emu:read16(VCOUNT)] = true
		end, p.rng)
	end
end

local function saveResume(p, c, fields)
	local base = string.format("%s_ss_%07d", p.out, c)
	emu:saveStateFile(base .. ".ss")
	local fh = io.open(base .. ".txt", "w")
	for k, v in pairs(fields) do fh:write(k, " ", tostring(v), "\n") end
	fh:close()
end

local function loadResume(base)
	emu:loadStateFile(base .. ".ss")
	local t = {}
	for line in io.lines(base .. ".txt") do
		local k, v = line:match("^(%S+) (%S+)")
		t[k] = tonumber(v)
	end
	return t
end

-- per-frame bookkeeping: trace row; snapshot/screens of the last frame of a game step; debugging dumps
local function account(p, keys, c)
	local vbl, seed = emu:read32(VBL), emu:read32(SEED)
	p.tbuf[#p.tbuf + 1] = string.pack("<I2I4I4I4", keys, c, vbl, seed)
	if #p.tbuf >= 4096 then p.trace:write(table.concat(p.tbuf)); p.tbuf = {} end
	if c ~= p.cprev and p.pend then              -- the previous step ended in the frame before: keep its snapshot
		p.snap:write(string.pack("<I4I4", p.pend[1], p.pend[2]), p.pend[3]); p.pend = nil
	end
	local m = c % p.n                             -- candidates are overwritten until the step's last frame
	if m == 0 then p.pend = {c, p.frames, snapshot()} end
	if m <= 2 then emu:screenshot(string.format("%s_%07d.png", p.out, c)) end   -- g+1, g+2: is a difference brief?
	if p.ramdump and c == p.ramdump then
		local fh = io.open(string.format("%s_ram_%07d.bin", p.out, c), "wb")
		fh:write(emu:readRange(0x02000000, 0x40000), emu:readRange(0x03000000, 0x8000))
		fh:close()
	end
	if p.d0 and c >= p.d0 and c <= p.d1 then
		local fh = io.open(string.format("%s_video_%07d.bin", p.out, c), "wb")
		fh:write(emu:readRange(0x07000000, 0x400), emu:readRange(0x05000000, 0x400),
		         emu:readRange(0x06000000, 0x18000), emu:readRange(0x04000000, 0x60))
		fh:close()
	end
	p.frames = p.frames + 1
	callerLog(p, c)
	if p.stop and c >= p.stop then closeOut(p, string.format("done %d %d", p.frames, c)) end
	return vbl, seed
end

local function stepRef(p)
	local c = emu:read32(STEP)
	account(p, p.keys, c)
	if not play then return end
	local adv = c ~= p.cprev
	p.cprev = c
	scanlineSample(p, c, adv)
	if p.left == 0 then
		p.ri = p.ri + 1
		if p.ri > #p.runs then closeOut(p, string.format("done %d %d", p.frames, c)); return end
		p.keys, p.left = p.runs[p.ri][1], p.runs[p.ri][2]
	end
	p.left = p.left - 1
	emu:setKeys(p.keys)
	if adv and p.save and c % p.save == 0 then saveResume(p, c, {ri = p.ri, left = p.left, keys = p.keys}) end
end

local function stepAlign(p)
	local c = emu:read32(STEP)
	local vbl, seed = account(p, p.keys, c)
	if not play then return end
	local C, V, R = p.C, p.V, p.R
	local adv = c ~= p.cprev
	if adv then
		if c ~= p.cprev + 1 then
			closeOut(p, string.format("err step jump %d -> %d at frame %d", p.cprev, c, p.frames)); return
		end
		-- reference frame index of the first frame that showed step c
		local e = p.e + 1
		while e <= p.last and C[e - 1] < c do e = e + 1 end
		if e > p.last then closeOut(p, string.format("done %d %d", p.frames, c)); return end
		if C[e - 1] ~= c then
			closeOut(p, string.format("err reference has no step %d (%d) at frame %d", c, C[e - 1], p.frames)); return
		end
		p.e = e
		-- seed after step cprev: replay = value saved at the previous frame, reference = last frame of that step
		local rr = R[e - 2]
		if p.rprev ~= rr then
			local scene = emu:read16(SCENE)
			-- realign only in scanline-RNG scenes and only when the seeds are a few calls apart (timing; all seen so
			-- far: <= 8); any other difference is a mismatch
			local k = p.scanrng[scene] and (lcgDist(rr, p.rprev, MAX_SHIFT) or
				(lcgDist(p.rprev, rr, MAX_SHIFT) and -lcgDist(p.rprev, rr, MAX_SHIFT)))
			local m = k and lcgDist(p.rprev, seed, 4000)
			if m then
				seed = lcgAdvance(rr, m)              -- keep the m calls made since then
				emu:write32(SEED, seed)
				p.fixes = p.fixes + 1
				p.log:write(string.format("rngfix step %d frame %d scene %d calls %+d\n", p.cprev, p.frames - 1, scene, k))
			else
				p.mism = p.mism + 1
				if p.mism <= 300 then
					p.log:write(string.format("rng step %d frame %d scene %d ref %08x got %08x\n", p.cprev, p.frames - 1,
						scene, rr, p.rprev))
				end
			end
		end
		local vr = V[e - 1]
		if vbl ~= vr then
			emu:write32(VBL, vr)
			p.log:write(string.format("vbl step %d frame %d %+d\n", c, p.frames - 1, vbl - vr))
		end
	else
		-- this frame lagged in the replay; if the reference lagged here too, follow it, else repeat its input
		if C[p.e] == C[p.e - 1] then p.e = p.e + 1 end
		if p.e > p.last then closeOut(p, string.format("done %d %d", p.frames, c)); return end
	end
	p.cprev, p.rprev = c, seed
	p.keys = p.K[p.e]
	emu:setKeys(p.keys)
	if adv and p.save and c % p.save == 0 then saveResume(p, c, {e = p.e, rprev = seed}) end
end

local function startRef(movie, out, n, state)
	local p = {runs = {}, ri = 0, left = 0, keys = 0, step = stepRef, scan = {}}
	for line in io.lines(movie) do
		local k, f = line:match("^(%d+)%s+(%d+)")
		if k then p.runs[#p.runs + 1] = {tonumber(k), tonumber(f)} end
	end
	local t = state and loadResume(state)
	openOut(p, out, n)
	p.rng = tonumber(env("PT_RNG"))
	if t then
		p.ri, p.left, p.keys = t.ri, t.left, t.keys
	else
		p.ri = 1; p.keys, p.left = p.runs[1][1], p.runs[1][2] - 1
	end
	emu:setKeys(p.keys)
	play = p
end

local function startAlign(trace, out, n, s, state)
	local p = {K = {}, C = {}, V = {}, R = {}, step = stepAlign, mism = 0, fixes = 0, scanrng = {}}
	local fh = io.open(trace, "rb"); local data = fh:read("a"); fh:close()
	local i, pos = 0, 1
	while pos + 13 <= #data do
		p.K[i], p.C[i], p.V[i], p.R[i], pos = string.unpack("<I2I4I4I4", data, pos)
		i = i + 1
	end
	data = nil; collectgarbage()
	p.last = i - 1
	if env("PT_SCANRNG") ~= "" then
		for line in io.lines(env("PT_SCANRNG")) do
			local scene = line:match("^(%d+)")
			if scene then p.scanrng[tonumber(scene)] = true end
		end
	end
	local t = state and loadResume(state)
	openOut(p, out, n)
	if t then
		p.e, p.rprev = t.e, t.rprev
	else
		p.e = s                                   -- trace frames 0..s-1 were played raw; frame s runs next
		if p.cprev ~= p.C[s - 1] then
			closeOut(p, string.format("err start step %d, reference %d", p.cprev, p.C[s - 1])); return
		end
		p.rprev = emu:read32(SEED)
	end
	p.keys = p.K[p.e]
	emu:setKeys(p.keys)
	play = p
end

local function handle(line)
	-- fields are separated by "|" when given (paths may contain spaces), else by whitespace
	local f = {}
	if line:find("|", 1, true) then
		for x in (line .. "|"):gmatch("([^|]*)|") do f[#f + 1] = x end
	else
		for x in line:gmatch("%S+") do f[#f + 1] = x end
	end
	local cmd, a, b, c, d = f[1], f[2] or "", f[3] or "", f[4] or "", f[5] or ""
	if cmd == "ping" then reply("pong")
	elseif cmd == "frame" then reply(tostring(emu:currentFrame()))
	elseif cmd == "wait" then waitUntil = tonumber(a); return
	elseif cmd == "keys" then emu:setKeys(tonumber(a)); reply("ok")
	elseif cmd == "r32" then reply(tostring(emu:read32(tonumber(a))))
	elseif cmd == "rr" then
		local s = emu:readRange(tonumber(a), tonumber(b))
		reply((s:gsub(".", function(ch) return string.format("%02x", ch:byte()) end)))
	elseif cmd == "w32" then emu:write32(tonumber(a), tonumber(b)); reply("ok")
	elseif cmd == "shot" then emu:screenshot(a); reply("ok")
	elseif cmd == "reset" then emu:reset(); reply("ok")
	elseif cmd == "load" then emu:loadStateFile(a); reply("ok")
	elseif cmd == "save" then emu:saveStateFile(a); reply("ok")
	elseif cmd == "ref" then startRef(a, b, tonumber(c))
	elseif cmd == "refstate" then startRef(a, b, tonumber(c), d)
	elseif cmd == "align" then startAlign(a, b, tonumber(c), tonumber(d))
	elseif cmd == "alignstate" then startAlign(a, b, tonumber(c), nil, d)
	else reply("err unknown " .. tostring(cmd)) end
end

local function pump()
	if not client then return end
	while true do
		local p, err = client:receive(4096)
		if p then buf = buf .. p
		else
			if err ~= socket.ERRORS.AGAIN then client = nil end
			break
		end
	end
end

-- emulation only advances during "wait" or an autonomous playback, so recordings are frame-exact
callbacks:add("frame", function()
	if play then
		local ok, msg = pcall(play.step, play)
		if not ok then play = nil; reply("err " .. tostring(msg):gsub("\n", " ")) end
		if play then return end
	end
	if waitUntil then
		waitUntil = waitUntil - 1
		if waitUntil <= 0 then waitUntil = nil; reply("ok") else return end
	end
	pump()
	while not waitUntil and not play do
		local line, rest = buf:match("^([^\n]*)\n(.*)$")
		if not line then
			if not client then break end
			pump()
		else
			buf = rest
			-- a script error must not leave the client waiting forever
			local ok, msg = pcall(handle, (line:gsub("\r", "")))
			if not ok then play = nil; waitUntil = nil; reply("err " .. tostring(msg):gsub("\n", " ")) end
		end
	end
end)

server = socket.bind(nil, PORT)
server:listen()
server:add("received", function()
	local cl = server:accept()
	if cl then client = cl; buf = "" end
end)
console:log("playthrough player listening on " .. PORT)
