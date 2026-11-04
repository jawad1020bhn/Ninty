@echo off
setlocal EnableExtensions
chcp 65001 >nul

REM =====================================================================
REM  The Gaffer - PES 2017 : prepare BEFORE / AFTER save-pair folders
REM  This script ONLY creates folders and tiny note files.
REM  It does NOT copy, move, edit, decrypt or touch any save file.
REM
REM  Usage:
REM     prepare_pairs.bat                 -> creates .\pes2017_pairs
REM     prepare_pairs.bat "D:\pairs"     -> creates D:\pairs
REM =====================================================================

set "ROOT=%~dp0pes2017_pairs"
if not "%~1"=="" set "ROOT=%~1"

set "SAVEDIR=%USERPROFILE%\Documents\KONAMI\Pro Evolution Soccer 2017\save"

echo.
echo  Preparing save-pair folders in:
echo    %ROOT%
echo.
echo  PES 2017 save folder (reference only - this script does NOT touch it):
echo    %SAVEDIR%
echo.

set "PAIRS=formation xi tactics contract budget my_offer forced_transfer loan youth training points"

for %%P in (%PAIRS%) do (
    mkdir "%ROOT%\%%P_before" 2>nul
    mkdir "%ROOT%\%%P_after"  2>nul

    >  "%ROOT%\%%P_before\PUT_ML00000011_HERE.txt" echo BEFORE: put the ORIGINAL encrypted ML00000011 here.
    >> "%ROOT%\%%P_before\PUT_ML00000011_HERE.txt" echo Restore this same original before starting EACH pair.
    >> "%ROOT%\%%P_before\PUT_ML00000011_HERE.txt" echo Do NOT copy EDIT00000000 here - it stays unchanged in "Needed files".

    >  "%ROOT%\%%P_after\PUT_ML00000011_HERE.txt" echo AFTER: put the encrypted ML00000011 here, saved from the SAME slot ML00000011.
    >> "%ROOT%\%%P_after\PUT_ML00000011_HERE.txt" echo Only ONE in-game change for this pair. Close PES 2017 before copying.

    >  "%ROOT%\%%P_after\_WHAT_I_CHANGED.txt" echo Pair: %%P
    >> "%ROOT%\%%P_after\_WHAT_I_CHANGED.txt" echo Change made (one line):
    >> "%ROOT%\%%P_after\_WHAT_I_CHANGED.txt" echo In-game date:
    >> "%ROOT%\%%P_after\_WHAT_I_CHANGED.txt" echo Slot: ML00000011
)

>  "%ROOT%\README.txt" echo PES 2017 BEFORE / AFTER SAVE PAIRS
>> "%ROOT%\README.txt" echo =================================
>> "%ROOT%\README.txt" echo One pair = ONE single change inside Master League.
>> "%ROOT%\README.txt" echo The original ML00000011 you already sent is the BEFORE for every pair.
>> "%ROOT%\README.txt" echo.
>> "%ROOT%\README.txt" echo For EVERY pair:
>> "%ROOT%\README.txt" echo   1. Put the original ML00000011 back in the save folder.
>> "%ROOT%\README.txt" echo   2. Start PES 2017, make ONE change, Save to slot ML00000011, quit the game.
>> "%ROOT%\README.txt" echo   3. Copy the new ML00000011 into the *_after folder.
>> "%ROOT%\README.txt" echo   4. Copy the original ML00000011 into the *_before folder.
>> "%ROOT%\README.txt" echo   5. Fill in _WHAT_I_CHANGED.txt
>> "%ROOT%\README.txt" echo.
>> "%ROOT%\README.txt" echo Never change two things in one pair. Never advance time in the same pair.
>> "%ROOT%\README.txt" echo Never modify EDIT00000000. Close the game before copying files.
>> "%ROOT%\README.txt" echo.
>> "%ROOT%\README.txt" echo Pairs and the ONE change for each:
>> "%ROOT%\README.txt" echo   formation         Formation 4-4-2 to 4-3-3
>> "%ROOT%\README.txt" echo   xi                Swap ONE player in the starting XI
>> "%ROOT%\README.txt" echo   tactics           Change ONE tactical option
>> "%ROOT%\README.txt" echo   contract          Renew ONE contract OR change ONE wage
>> "%ROOT%\README.txt" echo   budget            Change the transfer budget OR salary budget
>> "%ROOT%\README.txt" echo   my_offer          Send ONE transfer offer from Birmingham City FC
>> "%ROOT%\README.txt" echo   forced_transfer   Complete ONE incoming transfer
>> "%ROOT%\README.txt" echo   loan              ONE loan in or out
>> "%ROOT%\README.txt" echo   youth             Promote ONE youth player
>> "%ROOT%\README.txt" echo   training          ONE training / development change
>> "%ROOT%\README.txt" echo   points            Play ONE match OR advance ONE day (do this LAST)
>> "%ROOT%\README.txt" echo.
>> "%ROOT%\README.txt" echo Priority if you only want a few: formation, xi, contract, budget.
>> "%ROOT%\README.txt" echo Already working without pairs: shirt numbers and AI-club negotiations.

echo.
echo  Done. %ROOT% is ready.
echo  Nothing was copied or changed in your PES 2017 save folder.
pause
