#!/usr/bin/env bash
# Dump the live OpenAPI schema to docs/openapi.json.
set -euo pipefail
mkdir -p docs
python -c "
import json, pathlib
from api.router import app
pathlib.Path('docs/openapi.json').write_text(json.dumps(app.openapi(), indent=2))
print('Wrote docs/openapi.json')
"
