"""Exercise installer control flow without network access or real PATH changes."""

import os
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).parents[1]


def shell_path(path):
    value = Path(path).as_posix()
    if os.name == "nt":
        return f"/{value[0].lower()}{value[2:]}"
    return value


@pytest.fixture
def shell_install(tmp_path):
    git_bash = Path("C:/Program Files/Git/bin/bash.exe")
    shell = str(git_bash) if git_bash.exists() else shutil.which("sh")
    if not shell:
        pytest.skip("A POSIX shell is required")
    commands = tmp_path / "commands"
    tools = tmp_path / "tool bin"
    commands.mkdir()
    tools.mkdir()
    log = tmp_path / "calls"
    uv = tmp_path / "uv-stub"
    uv.write_text(
        '#!/bin/sh\nprintf "%s\\n" "$@" >> "$INSTALL_LOG"\n'
        'case "$1 $2" in\n'
        '  "tool install") exit "${INSTALL_EXIT:-0}" ;;\n'
        '  "tool dir") printf "%s\\n" "$TOOL_BIN" ;;\n'
        '  "tool update-shell") exit "${PATH_EXIT:-0}" ;;\nesac\n'
    )
    uv.chmod(0o755)
    shutil.copy(uv, commands / "uv")
    (commands / "uname").write_text('#!/bin/sh\necho "${TEST_OS:-Linux}"\n')
    (tools / "tukey").write_text('#!/bin/sh\necho "tukey 0.2.0"\n')
    (commands / "curl").write_text(
        '#!/bin/sh\n[ "${DOWNLOAD_EXIT:-0}" = 0 ] || exit "$DOWNLOAD_EXIT"\n'
        'while [ "$1" != --output ]; do shift; done\n'
        "cat > \"$2\" <<'BOOTSTRAP'\n"
        'mkdir -p "$UV_INSTALL_DIR"\n'
        'cp "$UV_STUB" "$UV_INSTALL_DIR/uv"\n'
        'chmod +x "$UV_INSTALL_DIR/uv"\nBOOTSTRAP\n'
    )
    for file in [*commands.iterdir(), tools / "tukey"]:
        file.chmod(0o755)
    env = {
        **os.environ,
        "HOME": shell_path(tmp_path),
        "UV_INSTALL_DIR": shell_path(tmp_path / "uv bin"),
        "UV_STUB": shell_path(uv),
        "INSTALL_LOG": shell_path(log),
        "TOOL_BIN": shell_path(tools),
    }

    def run(*, bootstrap=False, **overrides):
        if bootstrap:
            (commands / "uv").unlink()
        return subprocess.run(
            [
                shell,
                "-c",
                'PATH="$1:/usr/bin:/bin"; export PATH; sh "$2" "$3"',
                "installer-test",
                shell_path(commands),
                shell_path(ROOT / "install.sh"),
                "/source with spaces",
            ],
            env={**env, **overrides},
            capture_output=True,
            text=True,
        )

    return run, log


@pytest.mark.parametrize("platform", ["Linux", "Darwin"])
def test_shell_installs_and_configures_path(shell_install, platform):
    run, log = shell_install
    result = run(TEST_OS=platform)
    assert result.returncode == 0, result.stderr
    assert "tukey 0.2.0" in result.stdout
    assert log.read_text().splitlines() == [
        "tool",
        "install",
        "--reinstall",
        "--python",
        "3.12",
        "/source with spaces",
        "tool",
        "dir",
        "--bin",
        "tool",
        "update-shell",
    ]


def test_shell_bootstraps_uv(shell_install):
    run, log = shell_install
    result = run(bootstrap=True)
    assert result.returncode == 0, result.stderr
    assert "Installing uv" in result.stdout
    assert "update-shell" in log.read_text()


def test_shell_download_failure_stops_installation(shell_install):
    run, log = shell_install
    result = run(bootstrap=True, DOWNLOAD_EXIT="7")
    assert result.returncode == 7
    assert not log.exists()


def test_shell_install_failure_does_not_change_path(shell_install):
    run, log = shell_install
    result = run(INSTALL_EXIT="17")
    assert result.returncode == 17
    assert "update-shell" not in log.read_text()
    assert "Tukey is installed" not in result.stdout


def test_shell_warns_when_profile_cannot_be_updated(shell_install):
    run, _ = shell_install
    result = run(PATH_EXIT="1")
    assert result.returncode == 0
    assert "Add " in result.stderr and "to your PATH" in result.stderr


def test_shell_rejects_unsupported_platform(shell_install):
    run, log = shell_install
    result = run(TEST_OS="MINGW64_NT")
    assert result.returncode == 1
    assert "install.ps1" in result.stderr
    assert not log.exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows PowerShell installer")
@pytest.mark.parametrize("failure", ["", "install", "update-shell"])
def test_powershell_installation_flow(tmp_path, failure):
    shell = shutil.which("powershell.exe")
    if not shell:
        pytest.skip("Windows PowerShell is required")
    log = tmp_path / "calls"
    harness = tmp_path / "harness.ps1"
    harness.write_text(
        """
$ErrorActionPreference = 'Stop'
function Get-Command { return [pscustomobject]@{Source = 'Test-Uv'} }
function Join-Path {
    param($Path, $ChildPath)
    if ($ChildPath -eq 'tukey.exe') { return 'Test-Tukey' }
    Microsoft.PowerShell.Management\\Join-Path $Path $ChildPath
}
function Test-Uv {
    Add-Content -LiteralPath $env:INSTALL_LOG -Value ($args -join '|')
    $global:LASTEXITCODE = 0
    if ($args[1] -eq $env:TEST_FAILURE) { $global:LASTEXITCODE = 17; return }
    if ($args[1] -eq 'dir') { return $env:TOOL_BIN }
}
function Test-Tukey {
    Add-Content -LiteralPath $env:INSTALL_LOG -Value 'version-check'
    $global:LASTEXITCODE = 0
    Write-Output 'tukey 0.2.0'
}
& $env:INSTALL_SCRIPT -Source 'C:\\source with spaces'
if (($env:Path -split ';') -notcontains $env:TOOL_BIN) { throw 'Session PATH was not updated' }
""",
        encoding="utf-8",
    )
    result = subprocess.run(
        [shell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(harness)],
        env={
            **os.environ,
            "INSTALL_SCRIPT": str(ROOT / "install.ps1"),
            "INSTALL_LOG": str(log),
            "TOOL_BIN": str(tmp_path / "tool bin"),
            "TEST_FAILURE": failure,
        },
        capture_output=True,
        text=True,
    )
    calls = log.read_text(encoding="utf-8-sig")
    assert "tool|install|--reinstall|--python|3.12|C:\\source with spaces" in calls
    if failure:
        assert result.returncode != 0
        assert "version-check" not in calls
        if failure == "install":
            assert "update-shell" not in calls
    else:
        assert result.returncode == 0, result.stderr
        assert "tool|update-shell" in calls
        assert "version-check" in calls
