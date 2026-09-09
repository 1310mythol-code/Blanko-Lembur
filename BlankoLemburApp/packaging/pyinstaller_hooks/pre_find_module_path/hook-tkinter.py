"""Find Tkinter's standard-library package even if the local Tcl probe fails.

The release build bundles Tcl/Tk data and DLLs explicitly.  Some local Python
installations cannot initialize Tcl during PyInstaller's analysis despite
containing all required runtime files, so the default hook would otherwise
remove the Tkinter package before it can be bundled.
"""

from pathlib import Path
import sys


def pre_find_module_path(hook_api):
    hook_api.search_dirs = [str(Path(sys.base_prefix) / "Lib")]
