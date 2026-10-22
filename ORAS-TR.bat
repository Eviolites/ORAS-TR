@echo off
setlocal EnableExtensions EnableDelayedExpansion
pushd "%~dp0"

if /I "%~1"=="--help" goto :help
if /I "%~1"=="-h" goto :help

set "PYTHON="
if exist ".venv\Scripts\python.exe" (
	.venv\Scripts\python.exe -c "import sys; raise SystemExit(sys.version_info >= (3, 15))"
	if not errorlevel 1 set "PYTHON=.venv\Scripts\python.exe"
	if errorlevel 1 (
		echo Existing .venv uses an unsupported Python version. Recreating it...
		rmdir /s /q .venv
	)
)
if not defined PYTHON (
	set "BOOTSTRAP="
	for /f "delims=" %%V in ('py -3.13 -c "import sys; print(str(sys.version_info[0]) + "." + str(sys.version_info[1]))" 2^>nul') do if "%%V"=="3.13" set "BOOTSTRAP=py -3.13"
	if not defined BOOTSTRAP for /f "delims=" %%V in ('py -3.12 -c "import sys; print(str(sys.version_info[0]) + "." + str(sys.version_info[1]))" 2^>nul') do if "%%V"=="3.12" set "BOOTSTRAP=py -3.12"
	if not defined BOOTSTRAP for /f "delims=" %%V in ('python -c "import sys; print(str(sys.version_info[0]) + "." + str(sys.version_info[1]))" 2^>nul') do if "%%V"=="3.13" set "BOOTSTRAP=python"
	if not defined BOOTSTRAP for /f "delims=" %%V in ('python -c "import sys; print(str(sys.version_info[0]) + "." + str(sys.version_info[1]))" 2^>nul') do if "%%V"=="3.12" set "BOOTSTRAP=python"
	if not defined BOOTSTRAP (
		echo Python 3.12 or 3.13 was not found. Trying the Python install manager...
		py install 3.13
		for /f "delims=" %%V in ('py -3.13 -c "import sys; print(str(sys.version_info[0]) + "." + str(sys.version_info[1]))" 2^>nul') do if "%%V"=="3.13" set "BOOTSTRAP=py -3.13"
	)
	if not defined BOOTSTRAP (
		echo Trying winget to install Python 3.13...
		where winget >nul 2>&1
		if errorlevel 1 goto :python_missing
		winget install --id Python.Python.3.13 -e --scope user --source winget --accept-source-agreements --accept-package-agreements
		if errorlevel 1 goto :failed
		if exist "!LocalAppData!\Programs\Python\Python313\python.exe" set "BOOTSTRAP=!LocalAppData!\Programs\Python\Python313\python.exe"
		if not defined BOOTSTRAP (
			for /f "delims=" %%V in ('py -3.13 -c "import sys; print(str(sys.version_info[0]) + "." + str(sys.version_info[1]))" 2^>nul') do if "%%V"=="3.13" set "BOOTSTRAP=py -3.13"
		)
		if not defined BOOTSTRAP goto :python_missing
	)
	echo Creating local .venv...
	!BOOTSTRAP! -m venv .venv
	if errorlevel 1 goto :failed
	if not exist ".venv\Scripts\python.exe" goto :failed
	set "PYTHON=.venv\Scripts\python.exe"
)

set "BACKEND_ARG="
if not "%~1"=="" set "BACKEND_ARG=--backend %~1"

echo Using Python interpreter:
"%PYTHON%" --version
"%PYTHON%" -c "import sys; print(sys.executable)"
if errorlevel 1 goto :failed

echo Installing requirements...
"%PYTHON%" resources/install_requirements.py %BACKEND_ARG%
if errorlevel 1 goto :failed

echo.
echo Starting translation...
"%PYTHON%" resources/ORAS-TR.py
if errorlevel 1 goto :failed

echo.
echo Translation finished.
set /p "EXIT_PROMPT=Press Enter to exit."
popd
exit /b 0

:help
echo Usage: ORAS-TR.bat [backend]
echo.
echo Backend values: auto, cuda, rocm, directml, cpu
echo Default: auto-detect the available backend.
set /p "EXIT_PROMPT=Press Enter to exit."
popd
exit /b 0

:failed
echo.
echo The setup or translation process failed.
set /p "EXIT_PROMPT=Press Enter to exit."
popd
exit /b 1

:python_missing
echo.
echo Python 3.12 or 3.13 could not be installed automatically.
echo Install Python 3.13 from https://www.python.org/downloads/ and run this file again.
set /p "EXIT_PROMPT=Press Enter to exit."
popd
exit /b 1