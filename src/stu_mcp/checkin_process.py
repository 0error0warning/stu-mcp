"""Start the Windows worker outside a disposable MCP client's Job Object."""
from __future__ import annotations

import subprocess


def worker_environment(env):
    # WMI would otherwise inherit its provider's environment. Pass only local runtime configuration.
    names = {"systemroot", "windir", "path", "pathext", "userprofile", "username", "userdomain",
             "homedrive", "homepath", "appdata", "localappdata", "temp", "tmp", "programfiles",
             "programfiles(x86)", "programdata", "commonprogramfiles", "commonprogramfiles(x86)",
             "stu_checkin_home", "pythonpath", "pythonioencoding"}
    return [f"{key}={value}" for key, value in env.items() if key.lower() in names]


def _create_with_wmi(args, env, cwd):
    import win32com.client

    service = win32com.client.GetObject(r"winmgmts:{impersonationLevel=impersonate}!\\.\root\cimv2")
    startup = service.Get("Win32_ProcessStartup").SpawnInstance_()
    startup.ShowWindow = 0
    startup.CreateFlags = (subprocess.CREATE_NO_WINDOW | 0x00000400 |  # CREATE_UNICODE_ENVIRONMENT
                           subprocess.CREATE_BREAKAWAY_FROM_JOB)
    startup.EnvironmentVariables = worker_environment(env)
    process = service.Get("Win32_Process")
    params = process.Methods_("Create").InParameters.SpawnInstance_()
    # Native Windows argv quoting; no shell, cmd.exe, PowerShell or credentials in the command.
    params.CommandLine = subprocess.list2cmdline(args)
    params.CurrentDirectory = str(cwd)
    params.ProcessStartupInformation = startup
    result = process.ExecMethod_("Create", params)
    if int(result.ReturnValue) != 0:
        raise OSError(int(result.ReturnValue), "Local worker launch failed")
    return int(result.ProcessId)


def launch_windows_worker(args, env, cwd):
    try:
        import pythoncom
        pythoncom.CoInitialize()
    except Exception:
        raise OSError("Windows independent worker launch unavailable") from None
    failed = False
    try:
        # COM objects are released in the inner function before apartment cleanup.
        return _create_with_wmi(args, env, cwd)
    except Exception:
        failed = True
    finally:
        pythoncom.CoUninitialize()
    if failed:
        raise OSError("Windows independent worker launch unavailable") from None
