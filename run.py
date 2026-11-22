"""Start the app with the theme patch applied first: python run.py [streamlit options]"""
import subprocess
import sys
from pathlib import Path

import theme_patch

if __name__ == "__main__":
    print("theme patch:", theme_patch.apply())
    sys.exit(subprocess.call([sys.executable, "-m", "streamlit", "run", str(Path(__file__).with_name("app.py")),
                              *sys.argv[1:]]))
