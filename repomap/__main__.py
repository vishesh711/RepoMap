import sys

if __package__ in (None, ""):
    # Run as `python3 repomap ...` (the folder itself) instead of `python3 -m repomap`:
    # make the package importable from its parent folder.
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from repomap.cli import main
else:
    from .cli import main

sys.exit(main())
