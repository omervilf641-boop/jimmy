# Types text into whatever window currently has focus.
#
# Uses SendInput with KEYEVENTF_UNICODE rather than SendKeys: SendKeys drops
# modifier keys unpredictably (a Ctrl+V came through as a bare "v" in testing)
# and cannot express Hebrew at all. SendInput injects the exact characters.
param([Parameter(Mandatory = $true)][string]$Text)

Add-Type @"
using System;
using System.Runtime.InteropServices;

public static class Typist {
    [StructLayout(LayoutKind.Sequential)]
    struct KEYBDINPUT {
        public ushort wVk; public ushort wScan; public uint dwFlags;
        public uint time; public IntPtr dwExtraInfo;
    }
    // The union in INPUT is sized by its largest member (MOUSEINPUT), so on x64
    // the whole struct must measure 40 bytes. Without the trailing padding
    // SendInput rejects the call and silently returns 0.
    [StructLayout(LayoutKind.Explicit)]
    struct INPUT {
        [FieldOffset(0)]  public uint type;
        [FieldOffset(8)]  public KEYBDINPUT ki;
        [FieldOffset(32)] public ulong padding;
    }

    [DllImport("user32.dll", SetLastError = true)]
    static extern uint SendInput(uint nInputs, INPUT[] pInputs, int cbSize);

    const uint INPUT_KEYBOARD = 1;
    const uint KEYEVENTF_KEYUP = 0x0002;
    const uint KEYEVENTF_UNICODE = 0x0004;

    public static uint Send(string text) {
        var list = new System.Collections.Generic.List<INPUT>();
        foreach (char c in text) {
            // newlines need the real Return key; Unicode injection ignores them
            if (c == '\n') {
                list.Add(Key(0x0D, '\0', 0));
                list.Add(Key(0x0D, '\0', KEYEVENTF_KEYUP));
                continue;
            }
            if (c == '\r') continue;
            list.Add(Key(0, c, KEYEVENTF_UNICODE));
            list.Add(Key(0, c, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP));
        }
        var arr = list.ToArray();
        return SendInput((uint)arr.Length, arr, Marshal.SizeOf(typeof(INPUT)));
    }

    static INPUT Key(ushort vk, char scan, uint flags) {
        var i = new INPUT();
        i.type = INPUT_KEYBOARD;
        i.ki = new KEYBDINPUT { wVk = vk, wScan = (ushort)scan, dwFlags = flags,
                                time = 0, dwExtraInfo = IntPtr.Zero };
        return i;
    }
}
"@

$sent = [Typist]::Send($Text)
Write-Output "sent=$sent expected=$($Text.Length * 2)"
