"""Native folder selection; cancellation and unavailable UI never invent a path."""
import json
import os
from pathlib import Path
import platform
import subprocess

WINDOWS = r'''
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
Add-Type -AssemblyName System.Windows.Forms
$owner = New-Object System.Windows.Forms.Form
$owner.Text = 'BlackCat folder owner'
$owner.ShowInTaskbar = $false
$owner.Opacity = 0
$owner.StartPosition = 'CenterScreen'
$null = $owner.Handle
$dialog = New-Object System.Windows.Forms.FolderBrowserDialog
$dialog.Description = $env:BLACKCAT_PICKER_TITLE
$dialog.ShowNewFolderButton = $true
if ($env:BLACKCAT_PICKER_INITIAL -and (Test-Path -LiteralPath $env:BLACKCAT_PICKER_INITIAL)) {
    $dialog.SelectedPath = $env:BLACKCAT_PICKER_INITIAL
}
$script:observed = $false
if ($env:BLACKCAT_PICKER_SELFTEST -in @('1', 'select')) {
    Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class BlackCatPickerTest {
 [DllImport("user32.dll")] public static extern IntPtr GetWindow(IntPtr h, uint cmd);
 [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
 [DllImport("user32.dll")] public static extern bool PostMessage(IntPtr h, uint m, IntPtr w, IntPtr l);
}
'@
    $timer = New-Object System.Windows.Forms.Timer
    $timer.Interval = 1000
    $timer.Add_Tick({
        $popup = [BlackCatPickerTest]::GetWindow($owner.Handle, 6)
        if ($popup -ne [IntPtr]::Zero -and $popup -ne $owner.Handle -and [BlackCatPickerTest]::IsWindowVisible($popup)) {
            $script:observed = $true
            if ($env:BLACKCAT_PICKER_SELFTEST -eq 'select') {
                $null = [BlackCatPickerTest]::PostMessage($popup, 0x0111, [IntPtr]1, [IntPtr]::Zero)
            } else {
                $null = [BlackCatPickerTest]::PostMessage($popup, 0x0010, [IntPtr]::Zero, [IntPtr]::Zero)
            }
            $timer.Stop()
        }
    })
    $timer.Start()
}
try {
    $answer = $dialog.ShowDialog($owner)
    if ($answer -eq [System.Windows.Forms.DialogResult]::OK) {
        @{status='selected'; path=$dialog.SelectedPath; native_window_observed=$script:observed} | ConvertTo-Json -Compress
    } else {
        @{status='cancelled'; path=$null; native_window_observed=$script:observed} | ConvertTo-Json -Compress
    }
} finally {
    if ($timer) { $timer.Stop(); $timer.Dispose() }
    $dialog.Dispose(); $owner.Dispose()
}
'''

MACOS = '''on run argv
try
  set chosen to choose folder with prompt (item 1 of argv)
  return POSIX path of chosen
on error number -128
  return "__BLACKCAT_CANCELLED__"
end try
end run'''

def pick(title='BlackCat：请选择保存文件夹', initial=None, self_test=False):
    system = platform.system()
    try:
        if system == 'Windows':
            import base64
            environment = os.environ.copy()
            environment.update(BLACKCAT_PICKER_TITLE=title, BLACKCAT_PICKER_INITIAL=str(initial or ''), BLACKCAT_PICKER_SELFTEST='select' if self_test == 'select' else ('1' if self_test else '0'))
            encoded = base64.b64encode(WINDOWS.encode('utf-16le')).decode('ascii')
            result = subprocess.run(['powershell.exe', '-NoLogo', '-NoProfile', '-STA', '-EncodedCommand', encoded], env=environment, capture_output=True, timeout=20 if self_test else 1800)
            if result.returncode:
                return {'status': 'unavailable', 'path': None, 'reason': '系统文件夹窗口无法打开；请手动指定目录。'}
            data = json.loads(result.stdout.decode('utf-8-sig').strip())
        elif system == 'Darwin':
            if self_test:
                return {'status': 'unverified', 'path': None, 'reason': 'macOS 需要人工实机验收。'}
            result = subprocess.run(['osascript', '-e', MACOS, title], capture_output=True, text=True, timeout=1800)
            if result.returncode:
                return {'status': 'unavailable', 'path': None, 'reason': 'Finder 选择窗口不可用；请手动指定目录。'}
            value = result.stdout.strip()
            data = {'status': 'cancelled', 'path': None} if value == '__BLACKCAT_CANCELLED__' else {'status': 'selected', 'path': value}
        else:
            return {'status': 'unavailable', 'path': None, 'reason': '本版目录窗口仅支持 Windows 和 macOS。'}
        if data['status'] == 'selected':
            path = Path(data['path']).resolve()
            if not path.is_dir():
                return {'status': 'unavailable', 'path': None, 'reason': '选择的目录不存在。'}
            data['path'] = str(path)
        return data
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return {'status': 'unavailable', 'path': None, 'reason': '未能完成目录选择；保持配置未完成，可手动指定目录。'}

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--title', default='BlackCat：请选择保存文件夹')
    parser.add_argument('--initial')
    parser.add_argument('--self-test', action='store_true')
    parser.add_argument('--self-test-select', action='store_true')
    args = parser.parse_args()
    print(json.dumps(pick(args.title, args.initial, 'select' if args.self_test_select else args.self_test), ensure_ascii=False))
