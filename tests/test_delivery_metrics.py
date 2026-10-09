"""Release-facing metrics distinguish denominators and evidence provenance."""
import workflow


def test_metrics_do_not_count_review_copies_or_changed_bytes_as_verified_delivery():
    rows = [
        {'study_type': 'Retrospective', 'result': {
            'status': 'passed', 'client_outputs': ['output/protocol.docx'],
            'delivery': {'confirmed': True}, 'elapsed_seconds': 30,
        }, 'quality': {'status': 'passed', 'warnings': [], 'resolved_evidence_cautions': [
            {'caution_sha256': 'reminders', 'disposition': 'faithful'}],
            'verification_evidence': {'content': {'lexical_review_cautions': [{'caution_sha256': 'reminders'}]}}},
         'recovery_actions': [{'triggering_finding': {'owner': 'drafting'},
                               'candidate_bytes_changed': True, 'target_bytes_changed': True}]},
        {'study_type': 'Prospective', 'result': {'status': 'review_required', 'elapsed_seconds': 60},
         'quality': {'status': 'blocked', 'warnings': []},
         'recovery_actions': [{'triggering_finding': {'owner': 'construction'},
                               'candidate_bytes_changed': True, 'target_bytes_changed': True}],
         'unnecessary_stop': True},
    ]
    report = workflow.delivery_reliability_metrics(rows, evidence_kind='controlled_fixture')
    assert report['complete_delivery'] == {'numerator': 1, 'denominator': 2}
    assert report['clean_delivery'] == {'numerator': 1, 'denominator': 1}
    assert report['dismissed_false_alarms'] == {'numerator': 1, 'denominator': 1}
    assert report['unnecessary_stops'] == {'numerator': 1, 'denominator': 1, 'unclassified': 1}
    assert report['repair_success_by_owner']['drafting'] == {'numerator': 1, 'denominator': 1}
    assert report['repair_success_by_owner']['construction'] == {'numerator': 0, 'denominator': 1}
    assert report['latency_seconds'] == {'measured_operations': 2, 'total': 90, 'mean': 45, 'maximum': 60}
    assert report['evidence_kind'] == 'controlled_fixture'
