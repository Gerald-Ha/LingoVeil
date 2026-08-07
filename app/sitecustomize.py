from __future__ import annotations
import sys
import types

class _Dummy:
    def __getattr__(self, _name):
        return _Dummy()

    def __call__(self, *_args, **_kwargs):
        return _Dummy()

gi = types.ModuleType("gi")

gi.require_version = lambda *_args, **_kwargs: None
repository = types.ModuleType("gi.repository")

repository.GLib = _Dummy()

repository.Gst = _Dummy()

gi.repository = repository
sys.modules.setdefault("gi", gi)

sys.modules.setdefault("gi.repository", repository)

tk = types.ModuleType("tkinter")

tk.ttk = _Dummy()

sys.modules.setdefault("tkinter", tk)

sys.modules.setdefault("tkinter.ttk", tk.ttk)

portal = types.ModuleType("portal_screencast")

portal.PortalScreenCast = _Dummy
sys.modules.setdefault("portal_screencast", portal)
