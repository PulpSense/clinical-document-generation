"""Probe report-expression contract only; no model, fallback or clinical credit."""
import ast
from pathlib import Path
import pytest


@pytest.mark.parametrize('failures, expected', [
    ([{'error_type': 'TimeoutExpired', 'cause_type': None}], True),
    ([{'error_type': 'TimeoutError', 'cause_type': None}], True),
    ([{'error_type': 'OwnedObserverLifetimeUnresolved', 'cause_type': 'TimeoutExpired'}], False),
    ([{'error_type': 'RuntimeError', 'cause_type': 'TimeoutExpired'}], False),
    ([{'error_type': 'ValueError', 'cause_type': None}], False),
    ([], False),
])
def test_probe_report_recognizes_direct_not_fatal_wrapped_timeout(failures, expected):
    # Execute the report's exact production expression without a paid observer.
    tree = ast.parse(Path(__file__).with_name('run_tui_visual_probe.py').read_text())
    record = next(n.value for n in ast.walk(tree) if isinstance(n, ast.Assign)
                  and any(isinstance(t, ast.Name) and t.id == 'record' for t in n.targets))
    expression = next(v for k, v in zip(record.keys, record.values)
                      if isinstance(k, ast.Constant) and k.value == 'delegated_timeout_observed')
    value = eval(compile(ast.Expression(expression), '<probe-report-expression>', 'eval'),
                 {'delegate_failures': failures})
    assert value is expected
