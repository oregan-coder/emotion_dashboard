"""Explicit-file research runner; no live APIs or production dashboard writes."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import sys

from research_adapter import parse_json, score_document, render_explanation


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')


def main(argv: list[str] | None = None) -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',type=Path,required=True,help='explicit typed input JSON')
    parser.add_argument('--output-dir',type=Path,required=True,help='new/empty independent research directory')
    parser.add_argument('--evidence-root',type=Path,help='allowed local source JSON root; defaults to input parent\'s parent')
    args=parser.parse_args(argv)
    try:
        source=args.input.resolve(strict=True)
        out=args.output_dir.resolve()
        root=(args.evidence_root or source.parent.parent).resolve(strict=True)
        if out.name.lower() in {'data','static','web'} or out == source.parent:
            raise ValueError('Use a dedicated research result directory, not the input/production directory')
        if out.exists() and any(out.iterdir()):
            raise ValueError('OUTPUT_NOT_EMPTY: no implicit overwrite')
        script=Path(__file__).resolve().parent
        rule_path=script/'02_权重与分档提案_未启用.json'
        raw_rules=rule_path.read_bytes()
        rule_hash=sha256(raw_rules).hexdigest()
        if rule_hash != (script/'accepted_proposal.sha256').read_text().strip():
            raise ValueError('RULE_CHANGE_REQUIRES_REVIEW: proposal file changed')
        doc=parse_json(source.read_bytes()); rules=parse_json(raw_rules)
        result=score_document(doc,input_dir=source.parent,evidence_root=root,rules=rules)
        result['provenance']={'input_file':str(source), 'input_sha256':sha256(source.read_bytes()).hexdigest(),
                              'proposal_sha256':rule_hash,
                              'implementation_sha256':{f:sha256((script/f).read_bytes()).hexdigest() for f in
                                ['reference_calculator.py','research_adapter.py','run_research.py']},
                              'built_at_utc':datetime.now(timezone.utc).isoformat(),
                              'observation_dates_not_inferred_from_run_time':True}
        out.mkdir(parents=True,exist_ok=True)
        write_json(out/'research_results.json',result)
        write_json(out/'b03_composition.json',result['b03_composition'])
        (out/'candidate_explanation.md').write_text(render_explanation(result),encoding='utf-8')
        log=(f"Input: {source}\nInput type: {result['input_type']}\n"
             f"Candidate: {result['candidate']['code']}\n"
             f"Scored items: {result['known_scored_item_count']}/12\n"
             f"Known subtotal: {result['known_subtotal']}\n"
             f"Research score: {result['research_score_proposal']}\n"
             "Formal strategy: NOT_ENABLED\n"
             "Local run completed; this is not market/source verification.\n")
        (out/'run.log').write_text(log,encoding='utf-8')
        write_json(out/'output_manifest.json',{'files':{p.name:sha256(p.read_bytes()).hexdigest()
                                                     for p in sorted(out.iterdir()) if p.is_file()}})
        print(log,end='')
        return 0
    except (ValueError,TypeError,KeyError,OSError,IndexError) as exc:
        print(f'RESEARCH_RUN_FAILED: {type(exc).__name__}: {exc}',file=sys.stderr)
        return 2


if __name__=='__main__':
    raise SystemExit(main())
