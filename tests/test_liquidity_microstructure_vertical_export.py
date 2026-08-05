import hashlib
import json

from liquidity_microstructure_vertical_helpers import arguments
from processing_signals.main.liquidity_microstructure import run_liquidity_microstructure_vertical


def test_atomic_export(tmp_path):
    path = tmp_path / "nested" / "screen.json"
    result = run_liquidity_microstructure_vertical(**arguments(export_path=path))
    payload = path.read_bytes()
    assert payload.endswith(b"\n") and json.loads(payload)["stage"] == "screen_contract"
    assert result["export"]["sha256"] == hashlib.sha256(payload).hexdigest() and not list(path.parent.glob("*.tmp"))
