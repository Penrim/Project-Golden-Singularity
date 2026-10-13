-- Playtest logger for the merged cartridge.
-- While Golden Sun 1 is running, any read from the lower 16 MiB (The Lost Age's area) means a pointer that was not
-- moved. Each new case is appended to <rom>_watch.log and a savestate is written next to the ROM so it can be
-- reproduced. Nothing is shown in game; just play normally.
--
-- Report hotkey: L + R + Select together saves reports/<time>.png (screenshot), <time>.ss (savestate),
-- <time>_vram/pal/oam/io.bin and the screenshots of the last ~10 seconds (<time>_recent_NN.png, oldest first).
-- For this, a screenshot is kept every 20 frames in reports/recent/ (rolling, 30 files).
local LO, HI = 0x08000100, 0x08FFFFFF
local romPath = nil
local logFile = nil
local mode = "?"
local seen = {}
local pendingState = nil
local count = 0

local function openLog()
	if logFile then return end
	local base = (emu:getGameTitle() or "rom"):gsub("[^%w]", "_")
	logFile = io.open("gsmerge_watch.log", "a")
	if logFile then
		logFile:write(os.date("== session %Y-%m-%d %H:%M:%S ") .. base .. "\n")
		logFile:flush()
	end
end

local REPORT_KEYS = 0x0304            -- Select (4) + R (256) + L (512)
local RECENT, RECENT_EVERY = 30, 20
local recentIdx, reportHeld, frameNo = 0, false, 0
os.execute('if not exist reports\\recent mkdir reports\\recent')

local function copyFile(src, dst)
	local i = io.open(src, "rb")
	if not i then return end
	local data = i:read("a")
	i:close()
	local o = io.open(dst, "wb")
	if o then o:write(data); o:close() end
end

local function report()
	local t = os.date("%Y%m%d_%H%M%S")
	local base = "reports/" .. t
	emu:screenshot(base .. ".png")
	emu:saveStateFile(base .. ".ss")
	for _, r in ipairs({{"vram", 0x06000000, 0x18000}, {"pal", 0x05000000, 0x400}, {"oam", 0x07000000, 0x400},
	                    {"io", 0x04000000, 0x60}}) do
		local fh = io.open(string.format("%s_%s.bin", base, r[1]), "wb")
		if fh then fh:write(emu:readRange(r[2], r[3])); fh:close() end
	end
	for k = 1, RECENT do                                   -- oldest first
		local idx = (recentIdx + k - 1) % RECENT
		copyFile(string.format("reports/recent/%02d.png", idx), string.format("%s_recent_%02d.png", base, k))
	end
	local fh = io.open(base .. "_info.txt", "w")
	if fh then
		fh:write(string.format("frame=%d mode=%s rom=%s\n", emu:currentFrame(), mode, emu:getGameTitle() or "?"))
		fh:close()
	end
	console:log("playtest: report saved as " .. base)
end

callbacks:add("frame", function()
	frameNo = frameNo + 1
	if frameNo % RECENT_EVERY == 0 then
		emu:screenshot(string.format("reports/recent/%02d.png", recentIdx))
		recentIdx = (recentIdx + 1) % RECENT
	end
	local keys = emu:getKeys()
	if keys & REPORT_KEYS == REPORT_KEYS then
		if not reportHeld then report() end
		reportHeld = true
	else
		reportHeld = false
	end
	local pc = emu:readRegister("pc")
	if pc >= 0x09000000 and pc < 0x09800000 then mode = "GS1"
	elseif pc >= 0x08000000 and pc < 0x09000000 then mode = "TLA" end
	if pendingState then
		emu:saveStateFile(pendingState)
		pendingState = nil
	end
end)

emu:setRangeWatchpoint(function(info)
	if mode ~= "GS1" then return end
	local pc = emu:readRegister("pc")
	local lr = emu:readRegister("lr")
	-- The Lost Age's own code (directly, or calling into BIOS/IWRAM helpers) -> TLA is running now
	-- (happens right after the chapter transition, before the per-frame mode check runs)
	if (pc >= 0x08000000 and pc < 0x09000000) or (lr >= 0x08000000 and lr < 0x09000000) then
		mode = "TLA"
		return
	end
	local key = string.format("%08x", pc)
	if seen[key] then return end
	seen[key] = true
	count = count + 1
	openLog()
	if logFile then
		logFile:write(string.format("frame=%d pc=%08x lr=%08x addr=%08x r0=%08x r1=%08x r2=%08x r3=%08x\n",
			emu:currentFrame(), pc, emu:readRegister("lr"), info.address, emu:readRegister("r0"),
			emu:readRegister("r1"), emu:readRegister("r2"), emu:readRegister("r3")))
		logFile:flush()
	end
	if count == 1 then pendingState = "gsmerge_watch_first.ss" end
	console:log("playtest: stray read logged at pc " .. key)
end, LO, HI, C.WATCHPOINT_TYPE.READ)

console:log("playtest logger active (report: L + R + Select)")
