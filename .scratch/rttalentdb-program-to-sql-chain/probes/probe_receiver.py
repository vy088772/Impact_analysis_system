"""Probe: give every call whose bound method is declared on SQLDbContext the
receiver type the C# host should report; re-rate; compare outcomes."""
import sys, collections, copy
from pathlib import Path
sys.path.insert(0, '.')
from tools import coverage_report as T
from service import coverage_report, scan_store, analyze_service

root = Path('data/repos/System_Dept_1/RTTalentDB/RTTalentDB')
sel = 'sqldbcontext-50a129cdf273'
scan = scan_store.get_or_scan(root, refresh=False)
patch = '--patch' in sys.argv
if patch:
    scan = copy.deepcopy(scan)
    for v in scan.db_invocations.values():
        for i in v:
            if (i.get('wrapper_method_identity') or '').startswith('SQLDbContext.') and not i.get('wrapper_receiver_type'):
                i['wrapper_receiver_type'] = 'SQLDbContext'
                i['wrapper_receiver_type_provenance'] = 'declaring_type'
rated = coverage_report.rate_scan_invocations(
    root, scan, catalog=analyze_service.load_sp_catalog('RTTalentDB'),
    external_wrapper_contract=T.load_external_wrapper_contract(sel),
    contract_registry=T.load_contract_registry(),
    wrapper_review_exclusions=T.load_wrapper_review_exclusions('RTTalentDB'),
    explicit_contract=sel)
inv = [i for v in rated.values() for i in v]
sqldb = [i for i in inv if (i.wrapper_method_identity or '').startswith('SQLDbContext.')]
print('patch' if patch else 'baseline', 'all', len(inv), 'SQLDbContext calls', len(sqldb))
print(collections.Counter((i.evidence.value, i.reason, i.wrapper_status) for i in sqldb).most_common())
print('with procedure_name', sum(1 for i in sqldb if i.procedure_name))
