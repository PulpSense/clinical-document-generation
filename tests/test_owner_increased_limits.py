"""Cumulative owner reauthorization never resets previously charged work."""
import json
from pathlib import Path
import pytest
import storage_retention as storage

def setup(tmp_path, monkeypatch):
 authority=tmp_path/'limits.json';authority.write_text(json.dumps({'authorization':'Owner approved increased limits on 2026-10-14; supersedes original overnight caps','original_started_at_utc':'2026-10-14T01:12:25.124854+00:00','deadline_utc':'2026-10-14T13:12:25.124854+00:00','study_operation_limit':20,'additional_probe_limit':6,'counts_are_cumulative_across_all_coordinators':True,'operation_deadline_seconds':2700,'delegated_visual_cap_seconds':240,'parent_visual_cap_seconds':480}))
 monkeypatch.setattr(storage,'OWNER_LIMITS_AUTHORITY',authority)
 monkeypatch.setattr(storage,'OWNER_LEDGER_ROOT',tmp_path)
 past=tmp_path/'past/attempts.json';past.parent.mkdir();past.write_text(json.dumps({'study_operations':[{}]*3,'capability_probes':[{}]*2}))
 path=tmp_path/'current/attempts.json';path.parent.mkdir()
 data={'limits':{'study_operations':20,'capability_probes':6},'deadline_utc':'2026-10-14T13:12:25.124854+00:00','limits_authority':{'path':str(authority),'sha256':storage.sha(authority)},'cumulative_ledger_paths':[str(path),str(past)],'study_operations':[{}]*2,'capability_probes':[{}]}
 path.write_text(json.dumps(data));return path,data,authority,past

def test_authority_and_all_coordinator_counts(tmp_path,monkeypatch):
 path,data,_,_=setup(tmp_path,monkeypatch)
 assert storage.owner_limits(data)=={'study_operations':20,'capability_probes':6,'deadline_utc':'2026-10-14T13:12:25.124854+00:00'}
 assert storage.owner_cumulative_counts(path,data)=={'study_operations_launched':5,'additional_capability_probes_launched':3}

def test_authority_change_denied(tmp_path,monkeypatch):
 _,data,authority,_=setup(tmp_path,monkeypatch);authority.write_text('{}')
 with pytest.raises(ValueError,match='authority'):storage.owner_limits(data)

def test_missing_history_and_duplicate_history_denied(tmp_path,monkeypatch):
 path,data,_,past=setup(tmp_path,monkeypatch);data['cumulative_ledger_paths'].append(str(past))
 with pytest.raises(ValueError,match='Duplicate'):storage.owner_cumulative_counts(path,data)
 data['cumulative_ledger_paths']=[str(path),str(past)];past.unlink()
 with pytest.raises((ValueError,OSError)):storage.owner_cumulative_counts(path,data)

def test_increased_caps_without_authority_denied():
 with pytest.raises(ValueError):storage.owner_limits({'limits':{'study_operations':20,'capability_probes':6},'deadline_utc':'2026-10-14T13:12:25.124854+00:00'})

def test_original_authority_keeps_original_bounds():
 assert storage.owner_limits({'limits':{'study_operations':10,'capability_probes':3},'deadline_utc':'2026-10-14T09:12:25.124854+00:00'})['study_operations']==10
