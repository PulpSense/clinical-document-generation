"""TUI evidence binding, without importing any candidate implementation."""
import hashlib
import json
import importlib
from pathlib import Path
import sys


def validate_tui_host_checks(report, identity, manifest=None, evidence_root=None):
    required = {'profile_login_and_installed_read_tool', 'bounded_reads_checkpoint_and_native_tools',
                'worker_descendant_cleanup', 'render_before_native_repair',
                'render_after_native_repair', 'local_exact_bytes'}
    if (not isinstance(report, dict) or report.get('schema_version') != 'hermes-tui-host-checks/v1'
            or report.get('status') != 'passed' or report.get('host_mode') != 'hermes-tui'
            or report.get('candidate_identity') != identity
            or report.get('recipient_delivery_verified') is not False
            or report.get('os_isolation_verified') is not False
            or not required <= set(report.get('checks', {}))
            or any(report['checks'][key].get('status') != 'passed' for key in required)):
        raise ValueError('Passing host checks bound to this exact installed candidate are required')
    if evidence_root is not None:
        inventory = report.get('evidence_inventory', {})
        if not inventory:
            raise ValueError('Host-check file evidence is missing')
        for relative, expected in inventory.items():
            path = evidence_root / relative
            if (Path(relative).is_absolute() or '..' in Path(relative).parts
                    or path.is_symlink() or not path.resolve().is_relative_to(evidence_root.resolve())
                    or not path.is_file() or path.stat().st_size != expected['bytes']
                    or hashlib.sha256(path.read_bytes()).hexdigest() != expected['sha256']):
                raise ValueError('Host-check file evidence changed or is unavailable')
    if manifest is not None:
        digest = hashlib.sha256(json.dumps(report, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        if digest != manifest.get('host_checks_sha256'):
            raise ValueError('Host-check evidence differs from the frozen manifest')



def load_installed_workflow(root):
    """Reject cached checkout modules, including dependencies loaded lazily."""
    root = root.resolve()
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(root / 'scripts'))
    workflow = importlib.import_module('workflow')
    for name in workflow.PRODUCTION_MODULES:
        if name == 'owned_observer_process.py':
            # This CLI-only subreaper is executed by its bound absolute path,
            # never imported into a parent process (which would adopt children).
            if Path(name).stem in sys.modules:
                raise ValueError('Standalone owned supervisor must not be imported')
            if not (root / 'scripts' / name).is_file() or (root / 'scripts' / name).is_symlink():
                raise ValueError('Installed owned supervisor is unavailable')
            continue
        module = importlib.import_module(Path(name).stem)
        if Path(module.__file__).resolve() != root / 'scripts' / name:
            raise ValueError(f'Imported a different installed candidate module: {name}')
    return workflow
