"""Set the persistent browser's requested page languages before Chromium starts."""
import json
from pathlib import Path
import tempfile

from runtime import ROOT

directory = ROOT / 'profile/Default'
directory.mkdir(mode=0o700, parents=True, exist_ok=True)
path = directory / 'Preferences'
preferences = json.loads(path.read_text()) if path.exists() else {}
languages = preferences.setdefault('intl', {})
desired = 'de-DE,de,en-US,en'
if any(languages.get(key) != desired for key in ('accept_languages', 'selected_languages')):
    languages.update(accept_languages=desired, selected_languages=desired)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', dir=directory, delete=False) as out:
            temporary = Path(out.name)
            json.dump(preferences, out, ensure_ascii=False, separators=(',', ':'))
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
