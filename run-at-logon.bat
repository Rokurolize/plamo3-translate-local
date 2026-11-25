@echo off
rem Internal wrapper for Windows Task Scheduler (not a user-facing entry point).
rem Call the single entry point; discard console output so the log cannot grow forever. Pure ASCII.
call "%~dp0start-plamo.bat" > NUL 2>&1
