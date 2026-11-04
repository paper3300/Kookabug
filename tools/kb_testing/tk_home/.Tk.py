# tkinter.Tk() profile: readprofile() runs $HOME/.Tk.py for every Tk(). kb_testing.display.tk_env
# sets HOME to this folder so test windows open on the monitor chosen by KOOKABUG_TEST_DISPLAY.
# ASCII only (readprofile opens this file with the locale encoding). See kb_testing/display.py.
import importlib.util as _kb_util
import os as _kb_os
import sys as _kb_sys

_kb_mod = _kb_sys.modules.get("_kb_test_display")
if _kb_mod is None:
    _kb_path = _kb_os.path.join(_kb_os.environ["HOME"], "..", "display.py")
    _kb_spec = _kb_util.spec_from_file_location("_kb_test_display", _kb_path)
    if _kb_spec is not None and _kb_spec.loader is not None:
        _kb_mod = _kb_util.module_from_spec(_kb_spec)
        _kb_sys.modules["_kb_test_display"] = _kb_mod
        _kb_spec.loader.exec_module(_kb_mod)
if _kb_mod is not None:
    _kb_mod.install_tk(globals()["self"])
