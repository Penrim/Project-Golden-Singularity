@echo off
rem Starts the DE cartridge (build\gsmerge_de.gba) in mGBA with the background logger.
rem If anything goes wrong in Golden Sun 1, build\gsmerge_watch.log appears. F1 loads the chapter-change demo.
rem Seen a glitch? Press L + R + Select: screenshot, savestate and the last 10 seconds go to build\reports\.
cd /d "%~dp0build"
start "" "%~dp0tools\mgba-dev\mGBA.exe" --script "%~dp0tools\playtest_watch.lua" "%~dp0build\gsmerge_de.gba"
