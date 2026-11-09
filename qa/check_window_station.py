import ctypes
import os

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

hwinsta = user32.GetProcessWindowStation()
buf = ctypes.create_unicode_buffer(256)
user32.GetUserObjectInformationW(hwinsta, 2, buf, 256, None)
winsta_name = buf.value

hdesk = user32.GetThreadDesktop(kernel32.GetCurrentThreadId())
buf2 = ctypes.create_unicode_buffer(256)
user32.GetUserObjectInformationW(hdesk, 2, buf2, 256, None)
desk_name = buf2.value

# Check if visible / interactive
is_interactive = False
flags = ctypes.c_uint()
if user32.GetUserObjectInformationW(hwinsta, 1, ctypes.byref(flags), ctypes.sizeof(flags), None):
    # WSF_VISIBLE = 1
    is_interactive = bool(flags.value & 1)

print(f"Window Station: {winsta_name}")
print(f"Desktop: {desk_name}")
print(f"Interactive (WSF_VISIBLE): {is_interactive}")

# Check current active console session
kernel32 = ctypes.windll.kernel32
active_console_session = kernel32.WTSGetActiveConsoleSessionId()
my_session = os.environ.get("SESSIONNAME", "N/A")
print(f"Active Console Session ID: {active_console_session}")

